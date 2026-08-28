Imports System.IO

Module app
    Sub Main()
        Dim root As String = AppDomain.CurrentDomain.BaseDirectory
        Dim updateDir As String = Path.Combine(root, "update")
        Dim updateScript As String = Path.Combine(root, "applyUpdate.cmd")

        ' If there's ever a .zip in the Update folder, run applyUpdate.cmd, wait for it to finish, then continue on to launch the app
        Try
            If Directory.Exists(updateDir) AndAlso
               Directory.EnumerateFiles(updateDir, "*.zip").Any() AndAlso
               File.Exists(updateScript) Then

                ' Run in a visible console window so applyUpdate.cmd's output is shown to the user as progress
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
        Catch ex As Exception
            ' If the update check fails, fall through to launching the app normally
        End Try

        Dim projectDir As String = Path.Combine(root, "pythonFiles")
        Dim pythonwPath As String = Path.Combine(projectDir, "python-embed", "pythonw.exe")
        Dim scriptPath As String = Path.Combine(projectDir, "app.pyw")

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
            Environment.Exit(1)
        End Try
    End Sub
End Module