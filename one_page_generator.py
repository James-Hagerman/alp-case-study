import json
import os
import sys
from datetime import date, timedelta

# import anthropic
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape
from supabase import create_client
import anthropic

# Pulling in target HOA_code
arg = sys.argv[1]

# Connecting environment for jinja
env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html", "xml"])
)
template = env.get_template("template.html")

# Loading in environment vairalbe from .env
load_dotenv()
db = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY']).schema('alp')
# client = anthropic.Anthropic()

# Defining constants 
TODAY = date.today().isoformat()
ALL_VENDORS = db.table('vendors_intake').select('*').execute().data
SOON = (date.today() + timedelta(days=90)).isoformat()

# Function to import data from supabase
def get_data(hoa_code):
    '''
    input: target hoa_code 
    output: json
    cleans json output and formats form the template
    '''
    response = db.table('hoas_export').select('*, board_members(*), vendor_hoas_junction(vendors_intake(*))').eq('hoa_code', hoa_code).execute().data
    if not response:
        sys.exit(f'No HOA found with code {hoa_code}')
    data = response[0]

    data['vendors'] = [v['vendors_intake'] for v in data['vendor_hoas_junction']]
    del data['vendor_hoas_junction']

    for m in data['board_members']:
        m['current'] = m['term_end'] is None or m['term_end'] >= TODAY

    return data


# Checking command line argument 
if arg == 'all':
    hoa_codes = [r['hoa_code'] for r in db.table('hoas_export').select('hoa_code').execute().data]
else:
    hoa_codes = [arg]


def flags(data, all_vendors, soon):
    flags = []
    # Missing fields
    for field, label in [('monthly_dues', 'Monthly dues'), 
                         ('unit_count', 'Unit count'),
                         ('reserve_balance', 'Reserve balance'),
                         ('fiscal_year_end', 'Fiscal year end'),
                         ('board_email', 'Board email')]:
        if data[field] is None:
            flags.append(f'{label} is missing from record.')

    # Reserve study 
    if not data['has_reserve_study']:
        flags.append('No reserve study on file.')
    elif not data['last_reserve_study']:
        flags.append('Reserve study is on file but its date is not recorded')
    else:
        due = str(int(data['last_reserve_study'][:4]) + 3) + data['last_reserve_study'][4:] 
        if due < TODAY:
            flags.append(f'Reserve study is overdue, last completed: {data['last_reserve_study']}, update was due {due}')
        elif due <= soon:
            flags.append(f'Reserve study update is due soon: {due}')

    # Fiscal year
    if data['fiscal_year_end']:
        months_left = (data['fiscal_year_end'] - date.today().month) % 12
        if months_left <= 1:
            flags.append('Fiscal year ends within a month: the budget should be sent out to the owners')
        elif months_left <= 3:
            flags.append(f'Fiscal year ends in {months_left} months')

    # Board members 
    board = data['board_members']
    current = [m for m in board if m['current']]
    expired = [m for m in board if not m['current']]
    ending_soon = [m for m in current if m['term_end'] and m['term_end'] <= soon]

    if not board:
        flags.append('No board members')
    elif not current:
        flags.append('No current board members: every term has expired')
    if expired:
        flags.append(f'{len(expired)} of {len(board)} board terms have expired')
    if ending_soon:
        flags.append(f"Board terms ending soon: {', '.join(m['full_name'] for m in ending_soon)}.")

    no_email = [m['full_name'] for m in current if not m['email']]
    if no_email:
        flags.append(f"Current board members with no email: {', '.join(no_email)}.")
    current_roles = {m['role'] for m in current}
    for role in ['President', 'Treasurer']:
        if role not in current_roles:
            flags.append(f'No current {role}.')

    # Vendors
    vendors = data['vendors']
    if not vendors:
        flags.append('No vendors linked to this association.')
    no_coi = [v['vendor_name'] for v in vendors if not v['coi_on_file']]
    if no_coi:
        flags.append(f"Missing insurance certificate (COI): {', '.join(no_coi)}.")

    # Vendor coverage
    linked_trades = {v['trade'] for v in vendors}
    for trade in sorted({v['trade'] for v in all_vendors if v['trade']} - linked_trades):
        nearby = [v['vendor_name'] for v in all_vendors
                  if v['trade'] == trade and v['service_area'] and data['city'] in v['service_area']]
        if nearby:
            flags.append(f"No {trade} vendor linked, but {', '.join(nearby)} serves {data['city']}.")
        else:
            flags.append(f"No {trade} vendor on file serves {data['city']}.")

    return flags

def summary(data, flags):
    if not os.environ.get('ANTHROPIC_API_KEY'):
        return '\n'.join(flags)
    prompt = f'''You are writing the "Areas to watch" section of a one-page profile for an HOA management company.

                        Association: {data['association_name']} ({data['hoa_code']}), {data['city']}, {data['unit_count'] or 'unknown'} units

                        Issues found by automated checks:
                        {chr(10).join('- ' + f for f in flags)}

                        Write 3 to 5 bullet points for the property manager.
                        - Most urgent first: legal or financial risk (overdue reserve study, no current board, budget deadlines, missing insurance) before missing data and vendor gaps.
                        - Combine related issues into one point instead of listing them separately.
                        - Each point is one sentence, under 25 words, and says what needs attention and why it matters.
                        - Use only the issues listed above. Do not invent numbers, names, dates or causes.
                        - If there are no issues, return the single line: No issues flagged.

                        Return only the points, one per line, with no bullet symbols, numbering, heading or extra text.'''
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model = 'claude-haiku-5-5',
            max_tokens = 4000,
            messages = [{'role': 'user', 'content': prompt}] )

        return ''.join(b.text for b in response.content if b.type == 'text')
    except Exception:
        return '\n'.join(flags)

# # Looping through target hoa codes and generating report
for hoa_code in hoa_codes:
    data = get_data(hoa_code)
    flags_list = flags(data, ALL_VENDORS, SOON)
    summary_result = summary(data, flags_list)
    context = {    'hoa': data,
                    'board': data['board_members'],
                    'vendors': data['vendors'],
                    'all_vendors': db.table('vendors_intake').select('*').execute().data,
                    'summary': summary_result.splitlines(),
                    'summary_source': '—',
                    'reserve_per_unit': data['reserve_balance'] / data['unit_count'] if data['reserve_balance'] is not None and data['unit_count'] else None,
                    'soon': (date.today() + timedelta(days=90)).isoformat(),
                    'generated_at': TODAY,
}
    html = template.render(context)
    # Creating output file and writing report(s)
    os.makedirs('output', exist_ok=True)
    with open(f'output/{hoa_code}.html', 'w', encoding='utf-8') as f:
        f.write(html)


