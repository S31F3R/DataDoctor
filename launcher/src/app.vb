Imports System.IO
Imports System.Text

Module app
    Function AppLogPath() As String
        Dim root As String = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Data Doctor",
            "logs")
        Try
            Directory.CreateDirectory(root)
        Catch
        End Try
        Return Path.Combine(root, "app.log")
    End Function

    Sub LogToApp(level As String, message As String)
        Try
            Dim line As String = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") &
                " [" & level & "] launcher: " & message & Environment.NewLine
            File.AppendAllText(AppLogPath(), line, New UTF8Encoding(False))
        Catch
        End Try
    End Sub

    Function HasUpdateZip(root As String) As Boolean
        For Each name As String In New String() {"updates", "Updates", "Update", "update"}
            Dim dir As String = Path.Combine(root, name)
            Try
                If Directory.Exists(dir) AndAlso Directory.EnumerateFiles(dir, "*.zip").Any() Then
                    Return True
                End If
            Catch
            End Try
        Next
        Return False
    End Function

    Sub FailAndExit(message As String)
        LogToApp("ERROR", message)
        Try
            MsgBox(
                message & vbCrLf & vbCrLf & "See the log:" & vbCrLf & AppLogPath(),
                MsgBoxStyle.Critical,
                "Launcher")
        Catch
        End Try
        Environment.Exit(1)
    End Sub

    Sub Main()
        Dim root As String = AppDomain.CurrentDomain.BaseDirectory
        Dim updateScript As String = Path.Combine(root, "applyUpdate.cmd")
        LogToApp("INFO", "start root=" & root)

        ' Zip in Update\ → start applyUpdate.cmd and EXIT. Do not wait: this
        ' process must unlock Data Doctor.exe so the cmd can replace it.
        ' applyUpdate.cmd starts this exe again when it finishes.
        Try
            If HasUpdateZip(root) AndAlso File.Exists(updateScript) Then
                LogToApp("INFO", "updates zip present — starting applyUpdate.cmd")
                Dim updatePsi As New ProcessStartInfo With {
                    .FileName = updateScript,
                    .WorkingDirectory = root,
                    .UseShellExecute = True,
                    .CreateNoWindow = False,
                    .WindowStyle = ProcessWindowStyle.Normal
                }
                Process.Start(updatePsi)
                Return
            End If
        Catch ex As Exception
            LogToApp("WARN", "applyUpdate handoff failed: " & ex.Message & " — launching app")
            ' Fall through to launching the app
        End Try

        Dim projectDir As String = Path.Combine(root, "pythonFiles")
        Dim pythonwPath As String = Path.Combine(projectDir, "python-embed", "pythonw.exe")
        Dim scriptPath As String = Path.Combine(projectDir, "app.pyw")

        If Not File.Exists(pythonwPath) OrElse Not File.Exists(scriptPath) Then
            FailAndExit(
                "Could not start." & vbCrLf & vbCrLf &
                "Need:" & vbCrLf & pythonwPath & vbCrLf & scriptPath)
        End If

        ' pythonw + CreateNoWindow: no console flash. app.pyw binds stderr to
        ' app.log. Wait a few seconds so an immediate python crash is visible
        ' instead of a silent return to the desktop.
        Dim psi As New ProcessStartInfo With {
            .FileName = pythonwPath,
            .Arguments = """" & scriptPath & """",
            .WorkingDirectory = projectDir,
            .UseShellExecute = False,
            .CreateNoWindow = True,
            .WindowStyle = ProcessWindowStyle.Hidden}
        Dim proc As Process = Nothing
        Try
            LogToApp("INFO", "starting " & pythonwPath & " " & scriptPath)
            proc = Process.Start(psi)
        Catch ex As Exception
            FailAndExit(ex.Message)
        End Try
        If proc Is Nothing Then
            FailAndExit("Process.Start returned nothing for pythonw.exe")
        End If
        LogToApp("INFO", "python pid=" & proc.Id.ToString())
        Try
            If proc.WaitForExit(8000) Then
                FailAndExit(
                    "Data Doctor exited immediately (code " &
                    proc.ExitCode.ToString() & ").")
            End If
        Catch ex As Exception
            LogToApp("WARN", "WaitForExit failed: " & ex.Message)
        End Try
        LogToApp("INFO", "python still running — handing off")
    End Sub
End Module
