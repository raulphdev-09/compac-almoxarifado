"""Allowlisted stock reports for COMPAC and the isolated CANTEOR runtime.

Quantities are stored as integer thousandths and leave this boundary as decimal
strings. Report readers never expose users, private audit details or attendance.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import json
import os
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response

from .db import connect


MAX_REPORT_ROWS = 50_000
FORMATS = ('csv', 'xlsx', 'pdf', 'docx')
TITLES = {'stock': 'Posição atual do estoque', 'movements': 'Movimentações',
          'loans': 'Empréstimos pendentes', 'materials': 'Materiais',
          'dashboard': 'Resumo do estoque'}
COMMON = {'q', 'material_id'}
FILTERS = {
    'stock': COMMON | {'location_id', 'work_id'},
    'materials': COMMON,
    'movements': COMMON | {'location_id', 'work_id', 'employee_id', 'type',
                           'purpose', 'source_type', 'date_from', 'date_to'},
    'loans': COMMON | {'location_id', 'work_id', 'employee_id', 'date_from', 'date_to'},
    'dashboard': COMMON | {'location_id', 'work_id', 'type', 'purpose',
                           'source_type', 'date_from', 'date_to'},
}
MOVEMENT_TYPES = {'ENTRADA', 'SAIDA', 'DEVOLUCAO', 'TRANSFERENCIA', 'AJUSTE'}
PURPOSES = {'CONSUMO', 'EMPRESTIMO', 'LEGACY_UNCLASSIFIED'}
SOURCES = {'COMPRA', 'SALDO_INICIAL', 'OUTROS', 'NF', 'NOTA_FISCAL', 'LEGACY_UNCLASSIFIED',
           'INVENTARIO_INICIAL', 'OUTRO_RECEBIMENTO'}


def begin_snapshot(db):
    """Must run before authentication or any other query in this transaction."""
    if db.postgres:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    else:
        db.execute('BEGIN')


def report_catalog():
    # Imported opening quantities are recorded as movements by the import service.
    return {'formats': list(FORMATS), 'exports': [
        {'entity': entity, 'title': title, 'formats': list(FORMATS),
         'filters': sorted(FILTERS[entity])} for entity, title in TITLES.items()
    ], 'imports': [{'entity': entity, 'formats': ['csv', 'xlsx']}
                   for entity in ('materials', 'movements')],
        'document_import': False,
        'definitions': {'available': 'Quantidade disponível no local.',
                        'borrowed': 'Pendência em aberto atribuída ao local de retirada.',
                        'total_control': 'Disponível + emprestado; somar somente dentro da mesma unidade.'}}


def validate_filters(entity, values):
    if entity not in TITLES:
        raise HTTPException(404, 'Relatório não encontrado.')
    unknown = set(values) - FILTERS[entity]
    if unknown:
        raise HTTPException(422, 'Filtro não permitido para este relatório: ' + ', '.join(sorted(unknown)))
    filters = {}
    for key, value in values.items():
        if value is None or value == '':
            continue
        if key.endswith('_id'):
            try:
                if isinstance(value, bool) or str(int(value)) != str(value) or int(value) < 1:
                    raise ValueError
                filters[key] = int(value)
            except (TypeError, ValueError):
                raise HTTPException(422, f'Filtro {key} inválido.') from None
        elif key in ('date_from', 'date_to'):
            try:
                filters[key] = date.fromisoformat(str(value)).isoformat()
            except ValueError:
                raise HTTPException(422, f'Data {key} inválida; use AAAA-MM-DD.') from None
        else:
            cleaned = str(value).strip()
            if len(cleaned) > (200 if key == 'q' else 40):
                raise HTTPException(422, f'Filtro {key} muito longo.')
            if key == 'type' and cleaned not in MOVEMENT_TYPES:
                raise HTTPException(422, 'Tipo de movimento inválido.')
            if key == 'purpose' and cleaned not in PURPOSES:
                raise HTTPException(422, 'Finalidade inválida.')
            if key == 'source_type' and cleaned not in SOURCES:
                raise HTTPException(422, 'Origem de entrada inválida.')
            if cleaned:
                filters[key] = cleaned
    if filters.get('date_from', '') > filters.get('date_to', '9999-12-31'):
        raise HTTPException(422, 'A data inicial deve ser anterior ou igual à final.')
    return filters


def request_filters(request, *, controls=()):
    result = {}
    for key, value in request.query_params.multi_items():
        if key in controls:
            continue
        if key in result:
            raise HTTPException(422, f'Filtro repetido: {key}.')
        result[key] = value
    return result


def quantity(raw):
    return format(Decimal(str(raw or 0)) / Decimal(1000), '.3f')


def _scope(organization_id, *aliases):
    if organization_id is None:
        return '', []
    organization_id = str(UUID(str(organization_id)))
    return ' AND ' + ' AND '.join(f'{alias}.organization_id=?' for alias in aliases), [organization_id] * len(aliases)


def _join_scope(organization_id, left, right):
    return f' AND {left}.organization_id={right}.organization_id' if organization_id is not None else ''


def _zone(db, organization_id):
    name = os.getenv('COMPAC_TIMEZONE', 'America/Sao_Paulo')
    if organization_id is not None:
        row = db.execute('SELECT time_zone FROM organizations WHERE id=?', (str(organization_id),)).fetchone()
        if not row:
            raise HTTPException(404, 'Organização não encontrada.')
        name = row['time_zone']
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise HTTPException(503, 'Fuso horário do relatório não configurado corretamente.') from None


def date_bounds(filters, zone):
    result = {}
    for key in ('date_from', 'date_to'):
        if key in filters:
            day = date.fromisoformat(filters[key])
            if key == 'date_to':
                try:
                    day += timedelta(days=1)
                except OverflowError:
                    raise HTTPException(422, 'Data final fora do intervalo permitido.') from None
            result[key] = datetime.combine(day, time.min, zone).astimezone(timezone.utc).isoformat()
    return result


def _period(db, alias, bounds):
    # Legacy timestamps are TEXT. Cast for PostgreSQL and normalize in SQLite
    # so offsets and alternate ISO separators have the same UTC semantics.
    expression = f'CAST({alias}.created_at AS TIMESTAMPTZ)' if db.postgres else f'julianday({alias}.created_at)'
    clauses, params = '', []
    for key, operator in (('date_from', '>='), ('date_to', '<')):
        if key in bounds:
            placeholder = 'CAST(? AS TIMESTAMPTZ)' if db.postgres else 'julianday(?)'
            clauses += f' AND {expression}{operator}{placeholder}'
            params.append(bounds[key])
    return clauses, params


def _material_filter(filters, alias='m'):
    sql, params = '', []
    if 'material_id' in filters:
        sql += f' AND {alias}.id=?'
        params.append(filters['material_id'])
    if 'q' in filters:
        # Searching is literal: '%' and '_' are not accidental wildcards.
        query = filters['q'].lower().replace('!', '!!').replace('%', '!%').replace('_', '!_')
        sql += f" AND (LOWER({alias}.code) LIKE ? ESCAPE '!' OR LOWER({alias}.description) LIKE ? ESCAPE '!')"
        params.extend(['%' + query + '%'] * 2)
    return sql, params


def _rows(db, sql, params, page=None):
    if page is not None:
        page['total'] = int(db.execute('SELECT COUNT(*) AS total FROM (' + sql + ') report_count', params).fetchone()['total'])
        return [dict(row) for row in db.execute(sql + ' LIMIT ? OFFSET ?', list(params) + [page['limit'], page['offset']])]
    result = [dict(row) for row in db.execute(sql + f' LIMIT {MAX_REPORT_ROWS + 1}', params)]
    if len(result) > MAX_REPORT_ROWS:
        raise HTTPException(413, 'Relatório excede 100.000 registros. Restrinja os filtros e tente novamente; nenhum registro foi exportado.')
    return result


def _stock(db, filters, organization_id, page=None):
    scope, params = _scope(organization_id, 'm')
    inner_scope, inner_params = _scope(organization_id, 'p')
    # Pair union retains loan-only locations after the available balance reaches
    # zero, and LEFT JOIN retains materials that have never moved.
    pair_scope, pair_params = _scope(organization_id, 'b')
    sql = f'''WITH pairs AS (
        SELECT b.material_id,b.location_id FROM balances b WHERE 1=1{pair_scope}
        UNION SELECT p.material_id,p.location_id FROM loans p WHERE p.quantity>0{inner_scope}
    ), pending AS (
        SELECT p.material_id,p.location_id,CAST(SUM(p.quantity) AS TEXT) borrowed_raw
        FROM loans p WHERE p.quantity>0{inner_scope} GROUP BY p.material_id,p.location_id
    ) SELECT m.id material_id,m.code,m.description material,m.unit,m.status,CAST(m.minimum_stock AS TEXT) minimum_stock,
        x.location_id,l.name location,l.work_id,w.name work,
        COALESCE(b.quantity,0) available_raw,COALESCE(p.borrowed_raw,'0') borrowed_raw
        FROM materials m LEFT JOIN pairs x ON x.material_id=m.id
        LEFT JOIN balances b ON b.material_id=m.id AND b.location_id=x.location_id{_join_scope(organization_id, 'b', 'm')}
        LEFT JOIN pending p ON p.material_id=m.id AND p.location_id=x.location_id
        LEFT JOIN locations l ON l.id=x.location_id{_join_scope(organization_id, 'l', 'm')}
        LEFT JOIN works w ON w.id=l.work_id{_join_scope(organization_id, 'w', 'm')}
        WHERE 1=1{scope}'''
    params = pair_params + inner_params + inner_params + params
    material_sql, material_params = _material_filter(filters)
    sql += material_sql
    params += material_params
    for key, column in (('location_id', 'x.location_id'), ('work_id', 'l.work_id')):
        if key in filters:
            sql += f' AND {column}=?'
            params.append(filters[key])
    rows = _rows(db, sql + ' ORDER BY m.description,m.id,l.name,x.location_id', params, page)
    for row in rows:
        available, borrowed = int(row.pop('available_raw')), int(row.pop('borrowed_raw'))
        row.update(available=quantity(available), borrowed=quantity(borrowed),
                   total_control=quantity(available + borrowed), quantity=quantity(available))
        row['minimum_stock'] = format(Decimal(str(row['minimum_stock'])), '.3f')
    return rows


def _materials(db, filters, organization_id, page=None):
    scope, params = _scope(organization_id, 'm')
    extra, values = _material_filter(filters)
    sql = f'''SELECT m.id,m.code,m.description,m.unit,c.name category,m.category_id,CAST(m.minimum_stock AS TEXT) minimum_stock,m.status,
        m.individualizable FROM materials m JOIN categories c ON c.id=m.category_id{_join_scope(organization_id,'c','m')}
        WHERE 1=1{scope}{extra} ORDER BY m.description,m.id'''
    rows = _rows(db, sql, params + values, page)
    for row in rows:
        row['minimum_stock'] = format(Decimal(str(row['minimum_stock'])), '.3f')
        row['individualizable'] = bool(row['individualizable'])
    return rows


def _legacy_metadata(db, rows):
    """Read only allowlisted provenance keys, never serialize audit records."""
    lookup = {}
    identifiers = [row['id'] for row in rows]
    for start in range(0, len(identifiers), 500):
        batch = identifiers[start:start + 500]
        for row in db.execute('SELECT record_id,details FROM audit WHERE entity=? AND record_id IN (' +
                              ','.join('?' for _ in batch) + ') ORDER BY id', ['movements'] + batch):
            try:
                data = json.loads(row['details'])
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict):
                allowed = {}
                if data.get('purpose') in PURPOSES:
                    allowed['purpose'] = data['purpose']
                if data.get('source_type') in SOURCES:
                    allowed['source_type'] = data['source_type']
                if isinstance(data.get('source_reference'), str):
                    allowed['source_reference'] = data['source_reference'][:500]
                lookup.setdefault(row['record_id'], {}).update(allowed)
    for row in rows:
        row.update(lookup.get(row['id'], {}))


def _movements(db, filters, bounds, organization_id, page=None):
    scope, params = _scope(organization_id, 'v')
    material_sql, material_params = _material_filter(filters)
    period_sql, period_params = _period(db, 'v', bounds)
    if organization_id is None:
        provenance = "CASE WHEN v.type='SAIDA' AND EXISTS(SELECT 1 FROM loans lp WHERE lp.movement_id=v.id) THEN 'EMPRESTIMO' WHEN v.type='SAIDA' THEN 'LEGACY_UNCLASSIFIED' ELSE NULL END purpose,NULL source_type,NULL source_reference"
    else:
        provenance = 'v.purpose,v.source_type,v.source_reference'
    sql = f'''SELECT v.id,v.type,v.material_id,m.code,m.description material,m.unit,v.quantity quantity_raw,
        v.origin_id,o.name origin,v.destination_id,d.name destination,v.employee_id,e.name employee,
        v.notes,v.created_at,{provenance}
        FROM movements v JOIN materials m ON m.id=v.material_id{_join_scope(organization_id,'m','v')}
        LEFT JOIN locations o ON o.id=v.origin_id{_join_scope(organization_id,'o','v')}
        LEFT JOIN locations d ON d.id=v.destination_id{_join_scope(organization_id,'d','v')}
        LEFT JOIN employees e ON e.id=v.employee_id{_join_scope(organization_id,'e','v')}
        WHERE 1=1{scope}{material_sql}{period_sql}'''
    params += material_params + period_params
    for key in ('employee_id', 'type'):
        if key in filters:
            sql += f' AND v.{key}=?'
            params.append(filters[key])
    if 'location_id' in filters:
        sql += ' AND (v.origin_id=? OR v.destination_id=?)'
        params += [filters['location_id']] * 2
    if 'work_id' in filters:
        sql += ' AND (o.work_id=? OR d.work_id=?)'
        params += [filters['work_id']] * 2
    if organization_id is not None:
        for key in ('purpose', 'source_type'):
            if key in filters:
                sql += f' AND v.{key}=?'
                params.append(filters[key])
    rows = _rows(db, sql + ' ORDER BY v.id DESC', params, page)
    if organization_id is None:
        _legacy_metadata(db, rows)
        rows = [row for row in rows if all(row[key] == filters[key] for key in ('purpose', 'source_type') if key in filters)]
    for row in rows:
        row['quantity'] = quantity(row.pop('quantity_raw'))
    return rows


def _loans(db, filters, bounds, organization_id, page=None):
    scope, params = _scope(organization_id, 'p')
    material_sql, material_params = _material_filter(filters)
    period_sql, period_params = _period(db, 'p', bounds)
    sql = f'''SELECT p.id,p.employee_id,e.name employee,p.material_id,m.code,m.description material,m.unit,
        p.location_id,l.name location,l.work_id,w.name work,p.quantity quantity_raw,p.due_date,p.movement_id,p.created_at
        FROM loans p JOIN materials m ON m.id=p.material_id{_join_scope(organization_id,'m','p')}
        JOIN employees e ON e.id=p.employee_id{_join_scope(organization_id,'e','p')}
        JOIN locations l ON l.id=p.location_id{_join_scope(organization_id,'l','p')}
        LEFT JOIN works w ON w.id=l.work_id{_join_scope(organization_id,'w','p')}
        WHERE p.quantity>0{scope}{material_sql}{period_sql}'''
    params += material_params + period_params
    for key, alias in (('employee_id', 'p'), ('location_id', 'p'), ('work_id', 'l')):
        if key in filters:
            sql += f' AND {alias}.{key}=?'
            params.append(filters[key])
    rows = _rows(db, sql + " ORDER BY COALESCE(p.due_date,'9999-12-31'),p.id", params, page)
    for row in rows:
        row['quantity'] = quantity(row.pop('quantity_raw'))
    return rows


def unit_totals(rows):
    totals = {}
    for row in rows:
        entry = totals.setdefault(row['unit'], {'available': Decimal(0), 'borrowed': Decimal(0), 'total_control': Decimal(0)})
        for key in entry:
            entry[key] += Decimal(row[key])
    return [{'unit': unit, **{key: format(value, '.3f') for key, value in totals[unit].items()}} for unit in sorted(totals)]


COLUMNS = {
    'stock': [('code','Código'),('material','Material'),('unit','Unidade'),('location','Local'),('work','Obra'),
              ('available','Disponível'),('borrowed','Emprestado'),('total_control','Total sob controle'),('minimum_stock','Estoque mínimo')],
    'materials': [('code','Código'),('description','Material'),('category','Categoria'),('unit','Unidade'),
                  ('minimum_stock','Estoque mínimo'),('status','Situação'),('individualizable','Individualizável')],
    'movements': [('id','Registro'),('created_at','Data UTC'),('type','Tipo'),('purpose','Finalidade'),
                  ('source_type','Origem da entrada'),('source_reference','Documento de origem'),('code','Código'),
                  ('material','Material'),('unit','Unidade'),('quantity','Quantidade'),('origin','Origem'),
                  ('destination','Destino'),('employee','Responsável'),('notes','Observações')],
    'loans': [('id','Pendência'),('employee','Responsável'),('code','Código'),('material','Material'),('unit','Unidade'),
              ('location','Local da retirada'),('work','Obra'),('quantity','Pendente'),('due_date','Prazo'),('created_at','Retirada UTC')],
    'dashboard': [('indicator','Indicador'),('unit','Unidade'),('value','Valor'),('definition','Definição')],
}
LABELS = {'q': 'Busca', 'material_id': 'Material (ID)', 'location_id': 'Local (ID)',
          'work_id': 'Obra (ID)', 'employee_id': 'Responsável (ID)', 'type': 'Tipo',
          'purpose': 'Finalidade', 'source_type': 'Origem da entrada',
          'date_from': 'Data inicial', 'date_to': 'Data final',
          'available': 'Disponível', 'borrowed': 'Emprestado', 'total_control': 'Total sob controle',
          'materials': 'Materiais ativos', 'open_loans': 'Pendências abertas', 'low_stock': 'Materiais abaixo do mínimo',
          'movement_count': 'Movimentações no período', 'today_movements': 'Movimentações hoje'}


def _dashboard(db, filters, bounds, organization_id, zone):
    position_filters = {key: value for key, value in filters.items() if key in FILTERS['stock']}
    stocks = _stock(db, position_filters, organization_id)
    loans = _loans(db, position_filters, {}, organization_id)
    movements = _movements(db, filters, bounds, organization_id)
    today = datetime.now(zone).date().isoformat()
    today_filters = {**filters, 'date_from': today, 'date_to': today}
    today_count = len(_movements(db, today_filters, date_bounds(today_filters, zone), organization_id))
    available_by_material, minimums = {}, {}
    for row in stocks:
        available_by_material[row['material_id']] = available_by_material.get(row['material_id'], Decimal(0)) + Decimal(row['available'])
        minimums[row['material_id']] = Decimal(row['minimum_stock'])
    counts = {'materials': len({row['material_id'] for row in stocks if row['status'] == 'ATIVO'}),
              'open_loans': len(loans), 'low_stock': sum(value < minimums[key] for key, value in available_by_material.items()),
              'movement_count': len(movements), 'today_movements': today_count}
    definitions = {'materials': 'Materiais ativos na posição atual filtrada.',
                   'open_loans': 'Pendências com quantidade maior que zero na posição atual.',
                   'low_stock': 'Materiais com disponível total menor que seu mínimo, dentro dos locais filtrados.',
                   'movement_count': 'Registros de movimentação no período e filtros informados; não representa quantidade.',
                   'today_movements': 'Registros de movimentação de hoje no fuso configurado, com os demais filtros de fluxo.'}
    rows = [{'indicator': key, 'unit': 'registros', 'value': str(value), 'definition': definitions[key]} for key, value in counts.items()]
    by_unit = unit_totals(stocks)
    for entry in by_unit:
        for key in ('available', 'borrowed', 'total_control'):
            rows.append({'indicator': key, 'unit': entry['unit'], 'value': entry[key],
                         'definition': report_catalog()['definitions'][key]})
    return rows, {**counts, 'by_unit': by_unit, 'definitions': definitions}


def get_report(db, entity, filters, organization_id=None, *, page=None):
    filters = validate_filters(entity, filters)
    zone = _zone(db, organization_id)
    bounds = date_bounds(filters, zone)
    if entity == 'stock':
        rows, summary = _stock(db, filters, organization_id, page), {}
        if page is None:
            summary['by_unit'] = unit_totals(rows)
    elif entity == 'materials':
        rows, summary = _materials(db, filters, organization_id, page), {}
    elif entity == 'movements':
        rows, summary = _movements(db, filters, bounds, organization_id, page), {}
    elif entity == 'loans':
        rows, summary = _loans(db, filters, bounds, organization_id, page), {}
        grouped = {}
        for row in rows:
            grouped[row['unit']] = grouped.get(row['unit'], Decimal(0)) + Decimal(row['quantity'])
        if page is None:
            summary['by_unit'] = [{'unit': unit, 'borrowed': format(amount, '.3f')} for unit, amount in sorted(grouped.items())]
    else:
        rows, summary = _dashboard(db, filters, bounds, organization_id, zone)
    # UUID/datetime from PostgreSQL must cross JSON and document boundaries safely.
    rows = [{key: value.isoformat() if isinstance(value, (date, datetime)) else str(value) if isinstance(value, UUID) else value
             for key, value in row.items()} for row in rows]
    metadata = {'generated_at': datetime.now(timezone.utc).isoformat(), 'filters': filters,
                'time_zone': str(zone), 'date_bounds_utc': bounds,
                'position': 'current', 'total_rows': page['total'] if page is not None else len(rows),
                'definitions': report_catalog()['definitions'],
                'period_definition': 'Datas incluem o dia final completo no fuso informado. Período filtra movimentações/retiradas; saldos são atuais.',
                'quantity_definition': 'Quantidades decimais com três casas; totais separados por unidade.'}
    if organization_id is not None:
        metadata['organization_id'] = str(organization_id)
    return {'entity': entity, 'title': TITLES[entity], 'columns': COLUMNS[entity],
            'rows': rows, 'summary': summary, 'metadata': metadata}


def export_response(report, format_name, prefix='compac'):
    from .document_formats import render_document
    if format_name not in FORMATS:
        raise HTTPException(422, 'Formato inválido. Use CSV, XLSX, PDF ou DOCX.')
    totals = {}
    for key, value in report['summary'].items():
        if key == 'by_unit':
            for entry in value:
                for name, amount in entry.items():
                    if name != 'unit':
                        totals[f'{LABELS.get(name, name)} ({entry["unit"]})'] = amount
        elif not isinstance(value, (dict, list)):
            totals[LABELS.get(key, key)] = value
    metadata = {**report['metadata'], 'totals': totals,
                'filters': {**{LABELS.get(key, key): value for key, value in report['metadata']['filters'].items()},
                            'Fuso horário': report['metadata']['time_zone'],
                            'Posição': 'Atual; disponível + emprestado = total sob controle.',
                            'Quantidades': 'Três casas decimais. Totais separados por unidade.'}}
    if 'date_from' in report['metadata']['filters'] or 'date_to' in report['metadata']['filters']:
        metadata['filters']['Período'] = report['metadata']['period_definition']
    try:
        rows = report['rows']
        if report['entity'] == 'dashboard':
            rows = [{**row, 'indicator': LABELS.get(row['indicator'], row['indicator'])} for row in rows]
        content, media_type, extension = render_document(format_name, report['title'], report['columns'], rows, metadata)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return Response(content, media_type=media_type, headers={
        'Content-Disposition': f'attachment; filename="{prefix}-{report["entity"]}.{extension}"',
        'Cache-Control': 'no-store'})


def register_report_routes(app, current_user):
    @app.get('/api/reports/catalog')
    def catalog(user=Depends(current_user)):
        return report_catalog()

    @app.get('/api/reports/{entity}/export')
    def export(entity: str, request: Request, user=Depends(current_user)):
        filters = request_filters(request, controls=('format',))
        format_name = request.query_params.get('format', 'csv').lower()
        if format_name not in FORMATS:
            raise HTTPException(422, 'Formato inválido. Use CSV, XLSX, PDF ou DOCX.')
        with connect(snapshot=True) as db:
            report = get_report(db, entity, filters)
        return export_response(report, format_name)

    @app.get('/api/reports/{entity}')
    def preview(entity: str, request: Request, user=Depends(current_user)):
        with connect(snapshot=True) as db:
            return get_report(db, entity, request_filters(request))
