Imports System.IO

' Data Doctor Windows launcher.
' Compile on Windows (Developer Command Prompt):
'   vbc /nologo /target:winexe /out:"..\Data Doctor.exe" /win32icon:..\DataDoctor.ico App.vb
'
' Layout this exe expects (install root = this .exe's folder):
'   Data Doctor.exe
'   applyUpdate.cmd
'   Update\*.zip          optional; applied before launch
'   Project Files\python-embed\pythonw.exe
'   Project Files\DataDoctor.pyw

Module App
    Sub Main()
        Dim root As String = AppDomain.CurrentDomain.BaseDirectory
        Dim updateDir As String = Path.Combine(root, "Update")
        Dim updateScript As String = Path.Combine(root, "applyUpdate.cmd")

        Try
            If Directory.Exists(updateDir) AndAlso
               Directory.EnumerateFiles(updateDir, "*.zip").Any() AndAlso
               File.Exists(updateScript) Then

                Dim updatePsi As New ProcessStartInfo With {
                    .FileName = updateScript,
                    .WorkingDirectory = root,
                    .UseShellExecute = True,
                    .CreateNoWindow = False,
                    .WindowStyle = ProcessWindowStyle.Normal
                }
                Dim updateProc As Process = Process.Start(updatePsi)
                If updateProc IsNot Nothing Then
                    updateProc.WaitForExit()
                End If
            End If
        Catch
            ' Fall through to launch
        End Try

        Dim projectDir As String = Path.Combine(root, "Project Files")
        Dim pythonwPath As String = Path.Combine(projectDir, "python-embed", "pythonw.exe")
        Dim scriptPath As String = Path.Combine(projectDir, "DataDoctor.pyw")

        If Not File.Exists(pythonwPath) OrElse Not File.Exists(scriptPath) Then
            ' Silent Exit(1) looks like "the launcher does nothing".
            Try
                Microsoft.VisualBasic.Interaction.MsgBox(
                    "Data Doctor could not start." & vbCrLf & vbCrLf &
                    "Need:" & vbCrLf & pythonwPath & vbCrLf & scriptPath,
                    MsgBoxStyle.Critical,
                    "Data Doctor")
            Catch
            End Try
            Environment.Exit(1)
        End If

        Dim psi As New ProcessStartInfo With {
            .FileName = pythonwPath,
            .Arguments = """" & scriptPath & """",
            .WorkingDirectory = projectDir,
            .UseShellExecute = False,
            .CreateNoWindow = True,
            .WindowStyle = ProcessWindowStyle.Hidden
        }
        Try
            Process.Start(psi)
        Catch
            Environment.Exit(1)
        End Try
    End Sub
End Module
