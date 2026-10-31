"""Metadata compartilhada de validação e formulários do catálogo."""
def field(label, kind='text', required=True, **options):
    return dict(label=label, kind=kind, required=required, **options)

ENTITIES = {
 'works': {'label':'Obras','fields':{
    'code':field('Código'), 'name':field('Nome'),
    'status':field('Situação','select',options=['ATIVA','CONCLUIDA','INATIVA'])}},
 'categories': {'label':'Categorias','fields':{
    'name':field('Nome'), 'description':field('Descrição','textarea',False)}},
 'locations': {'label':'Localizações','fields':{
    'name':field('Nome'), 'work_id':field('Obra','relation',False,relation='works')}},
 'employees': {'label':'Funcionários','fields':{
    'registration':field('Matrícula'), 'name':field('Nome'), 'job_title':field('Cargo'),
    'work_id':field('Obra','relation',False,relation='works'),
    'status':field('Situação','select',options=['ATIVO','INATIVO'])}},
 'materials': {'label':'Materiais','fields':{
    'code':field('Código'), 'description':field('Descrição'),
    'category_id':field('Categoria','relation',relation='categories'),
    'unit':field('Unidade','select',options=['UN','PAR','KG','L','M','M2','M3','CX','PCT']),
    'minimum_stock':field('Estoque mínimo global','number',minimum=0),
    'individualizable':field('Controlar patrimônio','boolean',False),
    'status':field('Situação','select',options=['ATIVO','INATIVO'])}},
 'equipment': {'label':'Patrimônio','fields':{
    'asset_tag':field('Número do patrimônio'),
    'material_id':field('Material','relation',relation='materials'),
    'location_id':field('Localização','relation',relation='locations'),
    'condition':field('Condição','select',options=['BOA','REGULAR','RUIM']),
    'status':field('Situação','select',options=['DISPONIVEL','EM_USO','MANUTENCAO','BAIXADO'])}},
 'expenses': {'label':'Gastos','fields':{
    'supplier':field('Fornecedor'), 'document_number':field('Documento',required=False),
    'purchase_date':field('Data da compra','date'),
    'material_id':field('Material','relation',relation='materials'),
    'work_id':field('Obra','relation',False,relation='works'),
    'quantity':field('Quantidade','number',minimum=0.001),
    'unit_cost':field('Custo unitário (R$)','number',minimum=0)}},
 'consumption_profiles': {'label':'Perfis de consumo','fields':{
    'work_id':field('Obra','relation',relation='works'), 'activity':field('Atividade'),
    'material_id':field('Material','relation',relation='materials'),
    'consumption_per_unit':field('Consumo por unidade produzida','number',minimum=0.001),
    'team':field('Equipe',required=False), 'shift':field('Turno',required=False)}},
 'production': {'label':'Produção','fields':{
    'work_id':field('Obra','relation',relation='works'), 'activity':field('Atividade'),
    'quantity_produced':field('Quantidade produzida','number',minimum=0.001),
    'produced_at':field('Data','date')}}
}
