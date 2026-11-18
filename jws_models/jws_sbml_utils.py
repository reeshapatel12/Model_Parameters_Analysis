"""Low-level SBML XML, MathML, and annotation utility functions."""
from __future__ import annotations

from urllib.parse import urlparse, unquote
import xml.etree.ElementTree as ET

from jws_config import RDF_RESOURCE, QUALIFIER_NAMESPACES as QNS

def local(tag):
    return tag.rsplit('}', 1)[-1]


def namespace(tag):
    return tag[1:].split('}', 1)[0] if tag.startswith('{') else ''


def child(el, tag):
    return next((c for c in el if local(c.tag) == tag), None)


def children(el, tag):
    return [c for c in el if local(c.tag) == tag]


def descendants_under(el, list_name, tag_name):
    parent = child(el, list_name)
    return children(parent, tag_name) if parent is not None else []


def cv_id(url):
    """Return standardized collection and accession without assuming annotation equivalence."""
    p = urlparse(unquote(url))
    path = p.path.lstrip('/')
    if p.netloc.lower().endswith('identifiers.org'):
        bits = path.split('/', 1)
        collection, accession = (bits + [''])[:2]
        collection = collection.lower()
        mapping = {'obo.chebi': 'ChEBI', 'chebi': 'ChEBI', 'obo.go': 'GO', 'go': 'GO',
                   'uniprot': 'UniProt', 'pubmed': 'PubMed', 'pubchem.compound': 'PubChem',
                   'kegg.compound': 'KEGG Compound', 'interpro': 'InterPro',
                   'taxonomy': 'NCBI Taxonomy', 'doi': 'DOI', 'ec-code': 'EC', 'sbo': 'SBO'}
        database = mapping.get(collection, collection)
        acc = accession.replace('CHEBI:', '', 1) if database == 'ChEBI' else accession
        acc = acc.replace('GO:', '', 1) if database == 'GO' else acc
        full_id = f'ChEBI:{acc}' if database == 'ChEBI' else (f'GO:{acc}' if database == 'GO' else (f'{database}:{acc}' if acc else database))
        return database, full_id
    host = p.netloc.replace('www.', '')
    if 'ncbi.nlm.nih.gov' in host and path.startswith('pubmed/'):
        return 'PubMed', 'PubMed:' + path.split('/')[1]
    return host or 'external', url


def rdf_links(el):
    """Only direct annotations belonging to the supplied element; not its children."""
    ann = child(el, 'annotation')
    if ann is None:
        return []
    links = set()
    for node in ann.iter():
        if namespace(node.tag) not in QNS:
            continue
        qualifier = local(node.tag)
        prefix = ('bqbiol' if namespace(node.tag) == QNS[0] else
                  'bqmodel' if namespace(node.tag) == QNS[1] else 'dc')
        for item in node.iter():
            uri = item.attrib.get(RDF_RESOURCE, '')
            if uri and uri.startswith(('https://', 'http://', 'urn:')):
                links.add((prefix + ':' + qualifier, uri))
    return sorted(links)


def math_expr(node):
    if node is None:
        return ''
    tag = local(node.tag)
    args = list(node)
    if tag in ('math', 'semantics'):
        return math_expr(args[0]) if args else ''
    if tag in ('ci', 'cn', 'csymbol', 'sep'):
        return ' '.join(''.join(node.itertext()).split())
    if tag == 'piecewise':
        parts = [math_expr(a) for a in args]
        return 'piecewise(' + '; '.join(parts) + ')'
    if tag == 'piece':
        return (math_expr(args[0]) if args else '') + ' if ' + (math_expr(args[1]) if len(args)>1 else '')
    if tag == 'otherwise':
        return 'otherwise ' + (math_expr(args[0]) if args else '')
    if tag == 'apply' and args:
        op = local(args[0].tag)
        vals = [math_expr(a) for a in args[1:]]
        if op in ('plus', 'times'):
            return '(' + (' + ' if op == 'plus' else ' * ').join(vals) + ')'
        if op == 'minus':
            return '(' + (' - '.join(vals) if len(vals)>1 else '-' + (vals[0] if vals else '')) + ')'
        if op == 'divide' and len(vals)>=2:
            return '(' + vals[0] + ' / ' + vals[1] + ')'
        if op == 'power' and len(vals)>=2:
            return '(' + vals[0] + ' ^ ' + vals[1] + ')'
        if op in ('eq','neq','gt','lt','geq','leq','and','or'):
            return '(' + (' ' + op + ' ').join(vals) + ')'
        if op == 'not' and vals:
            return 'not(' + vals[0] + ')'
        if op in ('exp','ln','log','root','abs','floor','ceiling','sin','cos','tan','piecewise'):
            return op + '(' + ', '.join(vals) + ')'
        if op == 'delay':
            return 'delay(' + ', '.join(vals) + ')'
        if op in ('ci','csymbol'):
            return math_expr(args[0]) + '(' + ', '.join(vals) + ')'
        return op + '(' + ', '.join(vals) + ')'
    if tag == 'lambda':
        return 'lambda(' + ', '.join(map(math_expr,args)) + ')'
    return (' '.join(''.join(node.itertext()).split()) if not args else
            tag + '(' + ', '.join(map(math_expr,args)) + ')')


def math_xml(math):
    return ET.tostring(math, encoding='unicode') if math is not None else ''


def numeric(s):
    if s is None or s == '':
        return ''
    try:
        return float(s)
    except (ValueError, TypeError):
        return s


def species_unit(el, model, compartments):
    amount = 'initialAmount' in el.attrib
    substance = el.get('substanceUnits') or model.get('substanceUnits', '')
    if amount or el.get('hasOnlySubstanceUnits') == 'true':
        return substance or 'not explicitly declared'
    comp = compartments.get(el.get('compartment',''))
    if comp is None:
        return 'not explicitly declared'
    dim = float(comp.get('spatialDimensions', '3'))
    attr = 'volumeUnits' if dim==3 else ('areaUnits' if dim==2 else ('lengthUnits' if dim==1 else ''))
    size_unit = comp.get('units') or (model.get(attr) if attr else '')
    return f'{substance}/{size_unit}' if substance and size_unit else 'not explicitly declared'


def ident(el, parent_map):
    primary = el.get('id') or el.get('variable') or el.get('symbol') or el.get('metaid') or el.get('name') or ''
    if not primary:
        primary = f"{local(el.tag)}:{list(parent_map).index(el)}"
    p = parent_map.get(el)
    while p is not None and local(p.tag) != 'model':
        if local(p.tag) == 'reaction':
            return p.get('id', '') + '::' + primary
        p = parent_map.get(p)
    return primary


