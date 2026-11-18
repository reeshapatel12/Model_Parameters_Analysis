"""JWS model catalog discovery across all paginated listing pages."""
from __future__ import annotations

from collections import Counter
import re
import time
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from jws_config import INDEX

def catalog(session, delay=0.15):
    """Enumerate every page (not just first page); return metadata, page status."""
    html = session.get(INDEX, timeout=45)
    html.raise_for_status()
    soup = BeautifulSoup(html.text, 'html.parser')
    page_numbers = [1] + [int(x) for x in re.findall(r'[?&]page=(\d+)', html.text)]
    last = max(page_numbers)
    if last > 10000:
        raise ValueError('Implausible catalog pagination detected')
    models, duplicate, page_audit = {}, Counter(), []
    for n in range(1, last+1):
        if n == 1:
            this = soup
        else:
            time.sleep(delay)
            r = session.get(INDEX, params={'page': n}, timeout=45)
            r.raise_for_status()
            this = BeautifulSoup(r.text, 'html.parser')
        found_on_page = []
        for a in this.select('a[href]'):
            u = urlparse(urljoin(INDEX, a['href']))
            if u.netloc not in ('jjj.mib.ac.uk', 'www.jjj.mib.ac.uk'):
                continue
            m = re.fullmatch(r'/models/([^/]+)/?', u.path)
            if not m:
                continue
            slug = m.group(1)
            if not re.fullmatch(r'[a-zA-Z0-9_.-]+', slug):
                continue
            tr = a.find_parent('tr')
            # The site navigation includes direct /models/<word>/ routes such
            # as /models/create/ and /models/upload/. Actual catalog entries
            # are rows in the model listing table.
            if tr is None:
                continue
            values = [x.get_text(' ', strip=True) for x in tr.find_all('td', recursive=False)] if tr else []
            row = {'Model': slug, 'Organism': values[1] if len(values)>1 else '',
                   'Tissue': values[2] if len(values)>2 else '',
                   'Process': values[3] if len(values)>3 else '',
                   'Model type': values[4] if len(values)>4 else ''}
            found_on_page.append(slug)
            duplicate[slug] += 1
            models.setdefault(slug, row)
        page_audit.append({'page': n, 'links': len(found_on_page), 'distinct_slugs': len(set(found_on_page)), 'url': INDEX+'?page='+str(n)})
        print(f'Catalog page {n}/{last}: {len(set(found_on_page))} models', flush=True)
        if not found_on_page:
            raise RuntimeError(f'Catalog page {n} empty; refusing to claim a complete inventory')
    return models, duplicate, page_audit



