Imports System.IO

Module app
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

    Sub Main()
        Dim root As String = AppDomain.CurrentDomain.BaseDirectory
        Dim updateScript As String = Path.Combine(root, "applyUpdate.cmd")

        ' Zip in Update\ → start applyUpdate.cmd and EXIT. Do not wait: this
        ' process must unlock Data Doctor.exe so the cmd can replace it.
        ' applyUpdate.cmd starts this exe again when it finishes.
        Try
            If HasUpdateZip(root) AndAlso File.Exists(updateScript) Then
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
        Catch
            ' Fall through to launching the app
        End Try

        Dim projectDir As String = Path.Combine(root, "pythonFiles")
        Dim pythonwPath As String = Path.Combine(projectDir, "python-embed", "pythonw.exe")
        Dim scriptPath As String = Path.Combine(projectDir, "app.pyw")

        If Not File.Exists(pythonwPath) OrElse Not File.Exists(scriptPath) Then
            Try
                MsgBox(
                    "Could not start." & vbCrLf & vbCrLf &
                    "Need:" & vbCrLf & pythonwPath & vbCrLf & scriptPath,
                    MsgBoxStyle.Critical,
                    "Launcher")
            Catch
            End Try
            Environment.Exit(1)
        End If

        ' Build the start info for a true no-console launch
        Dim psi As New ProcessStartInfo With {
            .FileName = pythonwPath,
            .Arguments = """" & scriptPath & """",
            .WorkingDirectory = projectDir,
            .UseShellExecute = False,
            .CreateNoWindow = True,
            .WindowStyle = ProcessWindowStyle.Hidden}
        Try
            Process.Start(psi)
        Catch ex As Exception
            Try
                MsgBox(ex.Message, MsgBoxStyle.Critical, "Launcher")
            Catch
            End Try
            Environment.Exit(1)
        End Try
    End Sub
End Module