Attribute VB_Name = "PoolDeskMacros"
' ============================================================================
' PoolDesk - reconciliation exception import & formatting macro (Module 10).
'
' ImportAndFormatExceptions imports the daily reconciliation exceptions CSV,
' highlights each break by severity (HIGH = red, MEDIUM = amber), and builds a
' break-type summary sheet. Attach ImportAndFormatExceptions to a button.
'
' Installation and the data source are described in excel/README.md.
' This is a learning portfolio artifact, not a production tool.
' ============================================================================
Option Explicit


Public Sub ImportAndFormatExceptions()
    Dim ws As Worksheet
    Dim csvPath As String
    Dim lastRow As Long, lastCol As Long, i As Long
    Dim sevCol As Long, typeCol As Long

    csvPath = ThisWorkbook.Path & Application.PathSeparator & "exceptions.csv"
    If Dir(csvPath) = "" Then
        MsgBox "exceptions.csv was not found next to this workbook." & vbCrLf & _
               "Copy reports/powerbi/recon_exception.csv next to this file " & _
               "and rename it exceptions.csv.", vbExclamation, "PoolDesk"
        Exit Sub
    End If

    ' (Re)create a clean Exceptions sheet.
    Application.DisplayAlerts = False
    On Error Resume Next
    ThisWorkbook.Sheets("Exceptions").Delete
    On Error GoTo 0
    Application.DisplayAlerts = True
    Set ws = ThisWorkbook.Sheets.Add
    ws.Name = "Exceptions"

    ' Import the CSV via a query table, then drop the query.
    With ws.QueryTables.Add(Connection:="TEXT;" & csvPath, _
                            Destination:=ws.Range("A1"))
        .TextFileParseType = xlDelimited
        .TextFileCommaDelimiter = True
        .TextFileConsecutiveDelimiter = False
        .Refresh BackgroundQuery:=False
        .Delete
    End With

    lastRow = ws.Cells(ws.Rows.Count, "A").End(xlUp).Row
    lastCol = ws.Cells(1, ws.Columns.Count).End(xlToLeft).Column
    If lastRow < 2 Then
        MsgBox "No exception rows found in exceptions.csv.", _
               vbInformation, "PoolDesk"
        Exit Sub
    End If

    ' Resolve columns by header name so the macro survives column reordering.
    sevCol = HeaderColumn(ws, "severity")
    typeCol = HeaderColumn(ws, "break_type")

    ' Style the header row.
    With ws.Range(ws.Cells(1, 1), ws.Cells(1, lastCol))
        .Font.Bold = True
        .Interior.Color = RGB(31, 78, 120)
        .Font.Color = RGB(255, 255, 255)
    End With
    ws.Rows(1).AutoFilter
    ws.Columns.AutoFit

    ' Highlight each row by severity.
    If sevCol > 0 Then
        For i = 2 To lastRow
            Select Case UCase$(Trim$(CStr(ws.Cells(i, sevCol).Value)))
                Case "HIGH"
                    ws.Range(ws.Cells(i, 1), ws.Cells(i, lastCol)) _
                      .Interior.Color = RGB(255, 199, 206)
                Case "MEDIUM"
                    ws.Range(ws.Cells(i, 1), ws.Cells(i, lastCol)) _
                      .Interior.Color = RGB(255, 235, 156)
            End Select
        Next i
    End If

    BuildSummary ws, typeCol, lastRow

    MsgBox "Imported " & (lastRow - 1) & " exception(s) and applied " & _
           "severity formatting." & vbCrLf & _
           "See the 'Break Summary' sheet for counts by break type.", _
           vbInformation, "PoolDesk"
End Sub


' Returns the 1-based column index of a header, or 0 if not found.
Private Function HeaderColumn(ws As Worksheet, headerName As String) As Long
    Dim c As Long, lastCol As Long
    lastCol = ws.Cells(1, ws.Columns.Count).End(xlToLeft).Column
    For c = 1 To lastCol
        If LCase$(Trim$(CStr(ws.Cells(1, c).Value))) = LCase$(headerName) Then
            HeaderColumn = c
            Exit Function
        End If
    Next c
    HeaderColumn = 0
End Function


' Builds a "Break Summary" sheet with counts per break type.
Private Sub BuildSummary(ws As Worksheet, typeCol As Long, lastRow As Long)
    Dim sumWs As Worksheet, counts As Object
    Dim key As Variant
    Dim i As Long, r As Long

    If typeCol = 0 Then Exit Sub

    Application.DisplayAlerts = False
    On Error Resume Next
    ThisWorkbook.Sheets("Break Summary").Delete
    On Error GoTo 0
    Application.DisplayAlerts = True
    Set sumWs = ThisWorkbook.Sheets.Add
    sumWs.Name = "Break Summary"

    Set counts = CreateObject("Scripting.Dictionary")
    For i = 2 To lastRow
        key = Trim$(CStr(ws.Cells(i, typeCol).Value))
        If Len(key) > 0 Then counts(key) = counts(key) + 1
    Next i

    sumWs.Range("A1").Value = "Break Type"
    sumWs.Range("B1").Value = "Count"
    sumWs.Range("A1:B1").Font.Bold = True

    r = 2
    For Each key In counts.Keys
        sumWs.Cells(r, 1).Value = key
        sumWs.Cells(r, 2).Value = counts(key)
        r = r + 1
    Next key
    sumWs.Cells(r, 1).Value = "TOTAL"
    sumWs.Cells(r, 2).Value = lastRow - 1
    sumWs.Range(sumWs.Cells(r, 1), sumWs.Cells(r, 2)).Font.Bold = True
    sumWs.Columns("A:B").AutoFit
End Sub
