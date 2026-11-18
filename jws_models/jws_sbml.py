"""Extract annotation and model tables from an SBML document."""
from __future__ import annotations

from collections import Counter
import xml.etree.ElementTree as ET

from jws_config import INDEX
from jws_sbml_utils import (child, descendants_under, ident, local, math_expr,
    math_xml, numeric, rdf_links, species_unit, cv_id)

def harvest_xml(slug, xml_bytes, meta, sbml_url=None, model_url=None):
    """Parse a model into independently linkable annotation, kinetics and parameter tables."""
    model_url = model_url or f'{INDEX}{slug}/'
    sbml_url = sbml_url or model_url + 'sbml/?download=1'
    root = ET.fromstring(xml_bytes)
    model = next((x for x in root if local(x.tag)=='model'), None)
    if model is None:
        raise ValueError('No SBML model element')
    parent_map = {c:p for p in model.iter() for c in p}
    compartments = {e.get('id'):e for e in descendants_under(model,'listOfCompartments','compartment')}
    initial_assign = {}
    for a in descendants_under(model,'listOfInitialAssignments','initialAssignment'):
        initial_assign[a.get('symbol','')] = math_expr(child(a,'math'))
    rate_rules = {}
    for a in list(descendants_under(model,'listOfRules','assignmentRule')) + list(descendants_under(model,'listOfRules','rateRule')):
        rate_rules[a.get('variable','')] = math_expr(child(a,'math'))
    globalpars = {p.get('id'):p for p in descendants_under(model,'listOfParameters','parameter')}
    reactions = {r.get('id'):r for r in descendants_under(model,'listOfReactions','reaction')}
    kinetics, params, elrows, linkrows, refs = [], [], [], [], []
    reaction_detail = {}
    for rid, rxn in reactions.items():
        kin = child(rxn,'kineticLaw')
        math = child(kin,'math') if kin is not None else None
        formula = math_expr(math)
        variables = set(' '.join(''.join(x.itertext()).split()) for x in math.iter() if local(x.tag)=='ci') if math is not None else set()
        local_pars = {}
        if kin is not None:
            for listname in ('listOfLocalParameters', 'listOfParameters'):
                for tagname in ('localParameter', 'parameter'):
                    for p in descendants_under(kin, listname, tagname):
                        local_pars[p.get('id','')] = p
        used = []
        for pid in sorted(variables):
            p = local_pars.get(pid)
            if p is None:
                p = globalpars.get(pid)
            if p is not None:
                used.append(f"{pid}={p.get('value', '?')} [{p.get('units', 'unit not explicitly declared')}]")
        def species_part(part, is_modifier=False):
            ls = child(rxn, part)
            if ls is None:
                return ''
            return '; '.join((s.get('species','') if is_modifier else
                              s.get('species','') + ' (' + s.get('stoichiometry','1') + ')')
                             for s in ls)
        reactants = species_part('listOfReactants')
        products = species_part('listOfProducts')
        modifiers = species_part('listOfModifiers',True)
        rxnlinks = rdf_links(rxn)
        kinetics.append([slug,rid,rxn.get('name',''),bool(rxnlinks),'; '.join(u for _,u in rxnlinks),
                         reactants,products,modifiers,formula,'; '.join(used),math_xml(math),sbml_url])
        reaction_detail[rid] = (formula,'; '.join(used),reactants,products,modifiers)
    # parameters, including global and local (whether or not they are annotated)
    allpars=list(globalpars.values())
    for r in reactions.values():
        k=child(r, 'kineticLaw')
        if k is None:
            continue
        for ln in ('listOfLocalParameters','listOfParameters'):
            for tagname in ('localParameter','parameter'):
                allpars.extend(descendants_under(k,ln,tagname))
    for p in allpars:
        pid = p.get('id','')
        pk = ident(p,parent_map)
        rxid = pk.split('::')[0] if '::' in pk else ''
        plinks = rdf_links(p)
        params.append([slug,'local' if rxid else 'global',rxid,pid,numeric(p.get('value')),
                       p.get('units') or 'not explicitly declared',bool(plinks),
                       '; '.join(sorted({q for q,u in plinks})),
                       '; '.join(cv_id(u)[1] for q,u in plinks),sbml_url])
    # all directly RDF-annotated model elements, preserving full URI and qualifier
    for el in model.iter():
        links = rdf_links(el)
        if not links:
            continue
        typ = local(el.tag)
        eid = ident(el,parent_map)
        if typ == 'model':
            for qualifier,uri in links:
                db,acc=cv_id(uri)
                refs.append([slug,qualifier,db,acc,uri,sbml_url])
            continue
        for qualifier, uri in links:
            db,acc = cv_id(uri)
            linkrows.append([slug,typ,eid,qualifier,db,acc,uri,sbml_url])
        numerical_prop = numerical_val = units = kinlaw = used = reactants = products = modifiers = ''
        notes=[]
        if typ == 'species':
            numerical_prop = 'initialConcentration' if 'initialConcentration' in el.attrib else ('initialAmount' if 'initialAmount' in el.attrib else '')
            numerical_val = numeric(el.get(numerical_prop)) if numerical_prop else ''
            units = species_unit(el,model,compartments)
            if el.get('hasOnlySubstanceUnits')=='true':
                notes.append('hasOnlySubstanceUnits=true')
            if el.get('boundaryCondition')=='true':
                notes.append('boundaryCondition=true')
        elif typ in ('parameter','localParameter'):
            numerical_prop,numerical_val='value',numeric(el.get('value'))
            units = el.get('units') or 'not explicitly declared'
        elif typ == 'compartment':
            numerical_prop,numerical_val='size',numeric(el.get('size'))
            dim=float(el.get('spatialDimensions','3'))
            defname='volumeUnits' if dim==3 else ('areaUnits' if dim==2 else 'lengthUnits')
            units=el.get('units') or model.get(defname) or 'not explicitly declared'
        elif typ == 'reaction':
            rid=el.get('id','')
            kinlaw,used,reactants,products,modifiers=reaction_detail.get(rid,('','','','',''))
        else:
            if 'value' in el.attrib:
                numerical_prop,numerical_val='value',numeric(el.get('value'))
            elif 'stoichiometry' in el.attrib:
                numerical_prop,numerical_val='stoichiometry',numeric(el.get('stoichiometry'))
        a = initial_assign.get(el.get('id','') or el.get('symbol',''),'')
        if a:
            notes.append('Initial assignment overrides literal initial value')
        if eid in rate_rules:
            notes.append('Assignment/rate rule: '+rate_rules[eid])
        elrows.append([None,slug,typ,eid,el.get('name',''),el.get('compartment',''),
                       '; '.join(sorted({q for q,u in links})),
                       '; '.join(cv_id(u)[1] for q,u in links),
                       '; '.join(u for q,u in links),numerical_prop,numerical_val,units,
                       kinlaw,used,reactants,products,modifiers,el.get('sboTerm',''),a,
                       '; '.join(notes),sbml_url,model_url])
    counter=Counter(x[2] for x in elrows)
    stats={'Directly annotated elements':len(elrows),
           'Annotated species':counter['species'],'Annotated reactions':counter['reaction'],
           'Total reactions':len(reactions),'Total parameters':len(params),
           'Direct RDF links':len(linkrows)}
    return {'Annotated Elements':elrows,'Annotation Links':linkrows,
            'Reaction Kinetics':kinetics,'Parameters':params,'Model References':refs},stats


