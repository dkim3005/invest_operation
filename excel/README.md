# PoolDesk — Excel / VBA component (Module 10)

`VBA_Macro.bas` is an Excel macro that turns the daily reconciliation
exceptions into a formatted, reviewable worksheet — the Excel-side companion to
the Python pipeline. It demonstrates the **VBA** skill the role asks for.

The macro is shipped as a `.bas` source file (not a binary `.xlsm`) so it can
be version-controlled and reviewed. Import it into a workbook to use it.

## What the macro does

`ImportAndFormatExceptions`:

1. Reads `exceptions.csv` from the same folder as the workbook.
2. Imports it into a clean **Exceptions** sheet.
3. Styles the header row and applies an auto-filter.
4. Highlights every break by severity — **HIGH = red, MEDIUM = amber**.
5. Builds a **Break Summary** sheet with counts per break type.
6. Reports the result in a message box.

Columns are located by header name, so the macro keeps working if the export
column order changes.

## The data source

`exceptions.csv` is the reconciliation-exception export the pipeline produces.
`run-all` writes the CSV exports at the end of the run; `export` refreshes them
on their own:

```bash
python main.py run-all          # runs the pipeline + writes the CSV exports
# or, if the pipeline has already run:
python main.py export           # just refreshes reports/powerbi/*.csv
```

Then copy the exception export next to the workbook and rename it:

```bash
cp reports/powerbi/recon_exception.csv excel/exceptions.csv
```

## Installing the macro

1. Open a new Excel workbook and save it as **`PoolDesk_Macro.xlsm`** in this
   `excel/` folder (macro-enabled workbook).
2. Press **Alt + F11** to open the VBA editor.
3. **File → Import File…** and choose `VBA_Macro.bas`.
   (A module named `PoolDeskMacros` appears.)
4. Close the editor. On the sheet, **Insert → Shapes** (or a Form Control
   button), then right-click it → **Assign Macro… → ImportAndFormatExceptions**.
5. Make sure `exceptions.csv` is in this folder, then click the button.

## Note

This is a learning portfolio artifact. In a real deployment the same step would
run inside the Power Automate flow (see `automate/flow_spec.md`) rather than as
a manual button click.
