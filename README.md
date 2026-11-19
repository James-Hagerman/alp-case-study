# HOA One-Pager Generator

## Setup

1. Install dependencies (Python 3.12):
   ```bash
   pipenv install -r requirements.txt
   pipenv shell
   ```
2. Copy `.env.example` to `.env` and fill in:
   ```
   SUPABASE_URL=https://<project-ref>.supabase.co
   SUPABASE_KEY=<Supabase secret key>
   ANTHROPIC_API_KEY=<Anthropic API key>
   ```

The data is already loaded in Supabase (schema `alp`). Re-run `alp_cleaning.ipynb` (Restart & Run All) only if you need to reload the tables from the raw CSVs.

## Usage

Generate one HOA:
```bash
python one_page_generator.py SR-01
```

Generate every HOA:
```bash
python one_page_generator.py all
```

Output is written to `output/<hoa_code>.html`. Open it in a browser; use Print → Save as PDF for a PDF 

The generator reads live from Supabase on every run, so re-running the command rebuilds the one-pager with the current data.






