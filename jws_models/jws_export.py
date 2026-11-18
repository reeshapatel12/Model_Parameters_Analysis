"""CSV and formatted XLSX output for the JWS extraction."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

from jws_config import HEADERS

def csv_output(out, table_name, rows, header):
    f = out/(table_name.lower().replace(' ','_')+'.csv')
    with f.open('w',newline='',encoding='utf-8-sig') as h:
        w=csv.writer(h)
        w.writerow(header)
        w.writerows(rows)
    return f


def xlsx_output(out, tables, readme, filename='jws_annotated_model_elements_full.xlsx'):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        print('openpyxl not available: CSV files were written; install openpyxl for XLSX',file=sys.stderr)
        return None
    wb=Workbook()
    read=wb.active
    read.title='Readme'
    header_fill=PatternFill('solid',fgColor='183D5D')
    header_font=Font(bold=True,color='FFFFFF')
    read.append(['Field','Value'])
    for key,value in readme.items():
        read.append([key,value])
    for cell in read[1]:
        cell.fill=header_fill
        cell.font=header_font
    read.row_dimensions[1].height=24
    read.column_dimensions['A'].width=28
    read.column_dimensions['B'].width=78
    read.freeze_panes='A2'
    for name,header in HEADERS.items():
        sheet=wb.create_sheet(name)
        sheet.append(header)
        for cell in sheet[1]:
            cell.fill=header_fill
            cell.font=header_font
        sheet.row_dimensions[1].height=27
        data=tables.get(name,[])
        for row in data:
            sheet.append(row)
        sheet.freeze_panes='A2'
        for i,h in enumerate(header):
            width=(40 if 'URL' in h or 'Annotation' in h or 'formula' in h.lower() or 'parameters' in h.lower() else
                   29 if h in ('Model','Element ID','Reaction ID','Element name','Reactants','Products','Modifiers','Error') else
                   19)
            from openpyxl.utils import get_column_letter
            sheet.column_dimensions[get_column_letter(i+1)].width=width
    result=out/filename
    wb.save(result)
    return result


