# Auris project instructions

## Python environment

- Use `D:\AI\Auris\reader\.venv` as the project's Python environment.
- Run Python commands from the repository root with
  `reader\.venv\Scripts\python.exe`, or from `reader` with
  `.venv\Scripts\python.exe`.
- Do not use the system `python` command for project tests, scripts, or
  dependency checks.
- Run the full test suite from `reader` with:
  `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`
