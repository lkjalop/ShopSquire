# Creates a benign .xlsm test file with a harmless macro
# Purpose: Email security platform attachment testing

$outputPath = "C:\AI\ShopSquire\tmp\Harbourside_Acquisition_Details_CONFIDENTIAL.xlsm"

$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false

$workbook = $excel.Workbooks.Add()

# Add some realistic-looking content
$sheet = $workbook.Sheets.Item(1)
$sheet.Name = "Summary"
$sheet.Cells.Item(1,1) = "Acquisition Summary"
$sheet.Cells.Item(2,1) = "Target Company"
$sheet.Cells.Item(2,2) = "Harbourside Ltd"
$sheet.Cells.Item(3,1) = "Valuation"
$sheet.Cells.Item(3,2) = "$85,000,000"
$sheet.Cells.Item(5,1) = "NOTICE: Enable macros to view full financial model."

# Add a harmless VBA macro - just shows a message box, nothing else
$vbaProject = $workbook.VBProject
$module = $vbaProject.VBComponents.Add(1)  # 1 = vbext_ct_StdModule
$module.Name = "AutoRun"
$module.CodeModule.AddFromString(@"
Sub Auto_Open()
    MsgBox "TEST FILE - Benign macro for security platform testing. No harmful actions taken.", vbInformation, "Security Test"
End Sub

Sub Workbook_Open()
    MsgBox "TEST FILE - Benign macro for security platform testing. No harmful actions taken.", vbInformation, "Security Test"
End Sub
"@)

# Save as macro-enabled workbook
$workbook.SaveAs($outputPath, 52)  # 52 = xlOpenXMLWorkbookMacroEnabled (.xlsm)
$workbook.Close($false)
$excel.Quit()

[System.Runtime.Interopservices.Marshal]::ReleaseComObject($excel) | Out-Null

Write-Host "Created: $outputPath"
Write-Host "File size: $((Get-Item $outputPath).Length) bytes"
