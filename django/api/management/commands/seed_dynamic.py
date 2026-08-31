import logging
import random
import time
import uuid
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from faker import Faker
from api.models import (
    DimData,
    DimPrograma,
    DimProjeto,
    DimTarefa,
    DimMaterial,
    DimFornecedor,
    DimSolicitacao,
    FatoTarefa,
    FatoEmpenho,
    FatoCompra,
)

logger = logging.getLogger(__name__)

STATUS_EM_ANDAMENTO = 'EM ANDAMENTO'
STATUS_CONCLUIDO = 'CONCLUIDO'
STATUS_NAO_INICIADA = 'NAO INICIADA'
STATUS_ATIVO = 'ATIVO'

STATUS_PLANEJAMENTO = 'PLANEJAMENTO'
STATUS_SUSPENSO = 'SUSPENSO'

PEDIDO_STATUS_ENTREGUE = 'ENTREGUE'
PEDIDO_STATUS_CANCELADO = 'CANCELADO'
PEDIDO_STATUS_ABERTO = 'ABERTO'
PEDIDO_STATUS_ENVIADO = 'ENVIADO'

SOLICITACAO_STATUS_PENDENTE = 'PENDENTE'
SOLICITACAO_STATUS_CANCELADA = 'CANCELADA'
SOLICITACAO_STATUS_REJEITADA = 'REJEITADA'
SOLICITACAO_STATUS_APROVADA = 'APROVADA'

PRIORIDADE_BAIXA = 'BAIXA'
PRIORIDADE_MEDIA = 'MEDIA'
PRIORIDADE_ALTA = 'ALTA'
PRIORIDADE_CRITICA = 'CRITICA'

CATEGORIAS_GLOBAIS = [
    'Componentes Eletrônicos',
    'Componentes Mecânicos',
    'Placas de Circuito Impresso',
    'Materiais de Solda',
    'Sensores',
    'Comunicação',
    'Mecatrônica',
]
MATERIAL_TIPOS = ['Módulo', 'Componente', 'Peça', 'Conjunto', 'Estrutura']
TAREFA_ACOES = ['Analisar', 'Desenvolver', 'Testar', 'Projetar', 'Revisar', 'Homologar']
TAREFA_OBJETOS = [
    'módulo',
    'sistema',
    'interface',
    'integração',
    'componente',
    'circuito',
]


class Command(BaseCommand):
    help = 'Popula o DW com dados dinâmicos utilizando Faker, respeitando regras de negócio.'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dim_data_cache = {}
        self.rng = random.Random()

    def add_arguments(self, parser):
        parser.add_argument(
            '--programs', type=int, default=1, help='Number of programs to create'
        )
        parser.add_argument(
            '--projects', type=int, default=3, help='Number of projects per program'
        )
        parser.add_argument(
            '--tasks', type=int, default=5, help='Number of tasks per project'
        )
        parser.add_argument(
            '--users', type=int, default=3, help='Number of users per project'
        )
        parser.add_argument(
            '--clear', action='store_true', help='Clear existing data before seeding'
        )
        parser.add_argument(
            '--seed',
            type=int,
            default=None,
            help='Optional RNG seed for reproducible data generation',
        )

    def _clear_database(self):
        start_clear = time.time()
        self.stdout.write(self.style.WARNING('Limpando dados existentes...'))
        FatoCompra.objects.all().delete()
        FatoEmpenho.objects.all().delete()
        FatoTarefa.objects.all().delete()
        DimSolicitacao.objects.all().delete()
        DimFornecedor.objects.all().delete()
        DimMaterial.objects.all().delete()
        DimTarefa.objects.all().delete()
        DimProjeto.objects.all().delete()
        DimPrograma.objects.all().delete()
        DimData.objects.all().delete()
        self.stdout.write(
            self.style.WARNING(
                f'Tabelas limpas em {time.time() - start_clear:.2f} segundos.'
            )
        )

    def _get_or_create_dim_data(self, dt_obj):
        if dt_obj in self.dim_data_cache:
            return self.dim_data_cache[dt_obj]
        dim_data, _ = DimData.objects.get_or_create(
            dia=dt_obj.day, mes=dt_obj.month, ano=dt_obj.year
        )
        self.dim_data_cache[dt_obj] = dim_data
        return dim_data

    def _random_date(self, start_dt, end_dt):
        delta = end_dt - start_dt
        if delta.days <= 0:
            return start_dt
        random_days = self.rng.randrange(delta.days)
        return start_dt + timedelta(days=random_days)

    def _create_fornecedores(self, num_fornecedores, fake, categorias_globais):
        global_fornecedores = {c: [] for c in categorias_globais}
        for _ in range(num_fornecedores):
            cat = self.rng.choice(categorias_globais)
            f = DimFornecedor.objects.create(
                codigo_fornecedor=uuid.uuid4().hex[:6].upper(),
                razao_social=fake.company()[:256],
                cidade=fake.city()[:256],
                estado=fake.state_abbr(),
                categoria=cat,
                status=STATUS_ATIVO,
            )
            global_fornecedores[cat].append(f)
        return global_fornecedores

    def _create_materiais(self, num_materiais, fake, categorias_globais):
        global_materiais = {c: [] for c in categorias_globais}
        for _ in range(num_materiais):
            cat = self.rng.choice(categorias_globais)
            m = DimMaterial.objects.create(
                codigo_material=uuid.uuid4().hex[:6].upper(),
                descricao=f"{self.rng.choice(MATERIAL_TIPOS)} de {cat} - {fake.bothify(text='???-####').upper()}"[
                    :256
                ],
                categoria=cat,
                fabricante=fake.company()[:256],
                custo_estimado=round(self.rng.uniform(5.0, 500.0), 2),
                status=STATUS_ATIVO,
            )
            global_materiais[cat].append(m)
        return global_materiais

    def _generate_empenhos_material(
        self,
        projeto,
        material,
        quantidade,
        pedido_date,
        entrega_prev_date,
        proj_end,
        counts,
    ):
        consumption_date = self._random_date(
            pedido_date, entrega_prev_date + timedelta(days=5)
        )

        target_qty = quantidade
        qty_consumed = 0
        num_empenhos = self.rng.randint(1, 5)

        for i in range(num_empenhos):
            remain = target_qty - qty_consumed
            if remain <= 0:
                break

            if i == num_empenhos - 1:
                qty = remain
            else:
                limit_qty = remain // 2
                qty = self.rng.randint(1, limit_qty) if limit_qty >= 1 else remain

            qty_consumed += qty

            FatoEmpenho.objects.create(
                quantidade_empenhada=qty,
                projeto=projeto,
                material=material,
                data_empenho=self._get_or_create_dim_data(consumption_date),
            )
            counts['empenhos'] += 1

            if consumption_date < proj_end:
                consumption_date = self._random_date(
                    consumption_date + timedelta(days=1), proj_end
                )

    def _generate_pedidos_material(
        self,
        projeto,
        material,
        cat,
        solicitacao,
        solic_date,
        proj_end,
        is_concluido,
        global_fornecedores,
        fake,
        counts,
    ):
        pedido_date = self._random_date(solic_date, proj_end)
        entrega_prev_date = pedido_date + timedelta(days=self.rng.randint(5, 30))
        today = timezone.now().date()

        if global_fornecedores[cat]:
            fornecedor = self.rng.choice(global_fornecedores[cat])
        else:
            fornecedor = DimFornecedor.objects.create(
                codigo_fornecedor=uuid.uuid4().hex[:6].upper(),
                razao_social=fake.company()[:256],
                cidade=fake.city()[:256],
                estado=fake.state_abbr(),
                categoria=cat,
                status=STATUS_ATIVO,
            )
            global_fornecedores[cat].append(fornecedor)

        if is_concluido:
            pedido_status = self.rng.choices(
                [PEDIDO_STATUS_ENTREGUE, PEDIDO_STATUS_CANCELADO], weights=[95, 5], k=1
            )[0]
        else:
            pedido_status = self.rng.choices(
                [
                    PEDIDO_STATUS_ABERTO,
                    PEDIDO_STATUS_CANCELADO,
                    PEDIDO_STATUS_ENTREGUE,
                    PEDIDO_STATUS_ENVIADO,
                ],
                weights=[15, 5, 55, 25],
                k=1,
            )[0]

        pedido = FatoCompra.objects.create(
            numero_pedido=uuid.uuid4().hex[:6].upper(),
            valor_total=round(material.custo_estimado * solicitacao.quantidade, 2),
            status=pedido_status,
            solicitacao=solicitacao,
            fornecedor=fornecedor,
            data_pedido=self._get_or_create_dim_data(pedido_date),
            data_previsao_entrega=self._get_or_create_dim_data(entrega_prev_date),
        )
        counts['pedidos'] += 1

        if pedido_status == PEDIDO_STATUS_ENTREGUE:
            self._generate_empenhos_material(
                projeto,
                material,
                solicitacao.quantidade,
                pedido_date,
                entrega_prev_date,
                proj_end,
                counts,
            )

    def _generate_solicitacoes_material(
        self,
        projeto,
        material,
        cat,
        proj_start,
        proj_end,
        proj_status,
        duration_ratio,
        global_fornecedores,
        fake,
        counts,
    ):
        max_batches = max(2, int(duration_ratio / 6))
        num_batches = self.rng.randint(1, max_batches)
        is_planejamento = proj_status == STATUS_PLANEJAMENTO
        is_concluido = proj_status == STATUS_CONCLUIDO

        for _ in range(num_batches):
            solic_date = self._random_date(proj_start, proj_end)

            if is_planejamento:
                solicitacao_status = self.rng.choices(
                    [
                        SOLICITACAO_STATUS_PENDENTE,
                        SOLICITACAO_STATUS_CANCELADA,
                        SOLICITACAO_STATUS_REJEITADA,
                    ],
                    weights=[80, 15, 5],
                    k=1,
                )[0]
            elif is_concluido:
                solicitacao_status = self.rng.choices(
                    [
                        SOLICITACAO_STATUS_APROVADA,
                        SOLICITACAO_STATUS_CANCELADA,
                        SOLICITACAO_STATUS_REJEITADA,
                    ],
                    weights=[90, 5, 5],
                    k=1,
                )[0]
            else:
                solicitacao_status = self.rng.choices(
                    [
                        SOLICITACAO_STATUS_PENDENTE,
                        SOLICITACAO_STATUS_CANCELADA,
                        SOLICITACAO_STATUS_REJEITADA,
                        SOLICITACAO_STATUS_APROVADA,
                    ],
                    weights=[20, 5, 5, 70],
                    k=1,
                )[0]

            solicitacao = DimSolicitacao.objects.create(
                numero_solicitacao=uuid.uuid4().hex[:6].upper(),
                projeto=projeto,
                material=material,
                quantidade=self.rng.randint(1, 1000),
                data_solicitacao=self._get_or_create_dim_data(solic_date),
                prioridade=self.rng.choice(
                    [
                        PRIORIDADE_BAIXA,
                        PRIORIDADE_MEDIA,
                        PRIORIDADE_ALTA,
                        PRIORIDADE_CRITICA,
                    ]
                ),
                status=solicitacao_status,
            )
            counts['solicitacoes'] += 1

            if solicitacao_status == SOLICITACAO_STATUS_APROVADA:
                self._generate_pedidos_material(
                    projeto,
                    material,
                    cat,
                    solicitacao,
                    solic_date,
                    proj_end,
                    is_concluido,
                    global_fornecedores,
                    fake,
                    counts,
                )

    def _generate_materiais_para_projeto(
        self,
        projeto,
        proj_start,
        proj_end,
        proj_status,
        duration_ratio,
        global_fornecedores,
        global_materiais,
        fake,
        counts,
        categorias_globais,
    ):
        # Calcula a quantidade de categorias e materiais com base na duração do projeto (duration_ratio em meses)
        max_cats_by_duration = max(
            1, min(len(categorias_globais), int(duration_ratio / 5))
        )
        min_cats = max(1, max_cats_by_duration // 2)
        num_cats_to_pick = self.rng.randint(min_cats, max_cats_by_duration)

        picked_cats = self.rng.sample(categorias_globais, num_cats_to_pick)

        for cat in picked_cats:
            if not global_materiais[cat]:
                continue

            max_mats_by_duration = max(2, min(15, int(duration_ratio / 2)))
            min_mats = max(1, max_mats_by_duration // 3)

            mats_available = len(global_materiais[cat])
            num_mat_in_cat = self.rng.randint(
                min(min_mats, mats_available), min(max_mats_by_duration, mats_available)
            )
            chosen_mats = self.rng.sample(global_materiais[cat], num_mat_in_cat)

            for material in chosen_mats:
                self._generate_solicitacoes_material(
                    projeto,
                    material,
                    cat,
                    proj_start,
                    proj_end,
                    proj_status,
                    duration_ratio,
                    global_fornecedores,
                    fake,
                    counts,
                )

    def _generate_fatos_tarefa(
        self, tarefa, t_status, task_start, task_end, project_users, counts
    ):
        if t_status == STATUS_NAO_INICIADA:
            return

        if t_status == STATUS_CONCLUIDO:
            target_hours = float(tarefa.estimativa)
        else:
            target_hours = float(tarefa.estimativa) * self.rng.uniform(0.1, 0.9)

        team_size = max(1, min(len(project_users), int(target_hours / 40) + 1))
        task_team = self.rng.sample(project_users, team_size)

        hours_created = 0.0
        while target_hours - hours_created > 0.01:
            execution_date = self._random_date(task_start, task_end)
            remaining = target_hours - hours_created

            horas = round(min(remaining, self.rng.uniform(2.0, 8.0)), 2)
            hours_created += horas

            FatoTarefa.objects.create(
                usuario=self.rng.choice(task_team),
                horas_trabalhadas=horas,
                tarefa=tarefa,
                data=self._get_or_create_dim_data(execution_date),
            )
            counts['fatos_tarefa'] += 1

    def _generate_tarefas(
        self,
        projeto,
        proj_start,
        proj_end,
        proj_status,
        scaled_tasks,
        project_users,
        fake,
        counts,
    ):
        is_concluido = proj_status == STATUS_CONCLUIDO
        is_planejamento = proj_status == STATUS_PLANEJAMENTO
        status_tarefa_choices = [
            STATUS_NAO_INICIADA,
            STATUS_EM_ANDAMENTO,
            STATUS_CONCLUIDO,
        ]

        for _ in range(scaled_tasks):
            estimativa_horas = self.rng.randint(2, 40)
            estimativa_dias = (estimativa_horas + 7) // 8

            max_start = proj_end - timedelta(days=estimativa_dias)
            if max_start < proj_start:
                max_start = proj_start

            task_start = self._random_date(proj_start, max_start)
            task_end = task_start + timedelta(days=estimativa_dias)

            responsavel_tarefa = (
                self.rng.choice(project_users) if project_users else fake.name()[:256]
            )

            if is_planejamento:
                t_status = STATUS_NAO_INICIADA
            elif is_concluido:
                t_status = STATUS_CONCLUIDO
            else:
                t_status = self.rng.choice(status_tarefa_choices)

            tarefa = DimTarefa.objects.create(
                codigo_tarefa=uuid.uuid4().hex[:6].upper(),
                projeto=projeto,
                titulo=f"{self.rng.choice(TAREFA_ACOES)} {self.rng.choice(TAREFA_OBJETOS)} {fake.bothify(text='??-##').upper()}"[
                    :256
                ],
                responsavel=responsavel_tarefa,
                estimativa=estimativa_horas,
                data_inicio=self._get_or_create_dim_data(task_start),
                data_fim_prevista=self._get_or_create_dim_data(task_end),
                status=t_status,
                lead_time_dias=self.rng.randint(0, 5),
                is_atrasado=self.rng.choice([True, False]),
            )
            counts['tarefas'] += 1

            self._generate_fatos_tarefa(
                tarefa, t_status, task_start, task_end, project_users, counts
            )

    def _process_projeto(
        self,
        programa,
        prog_start,
        prog_end,
        options,
        fake,
        categorias_globais,
        global_fornecedores,
        global_materiais,
    ):
        project_duration_days = self.rng.randint(180, 1095)
        max_start_date = prog_end - timedelta(days=project_duration_days)

        if max_start_date <= prog_start:
            proj_start = prog_start
            proj_end = prog_end
        else:
            proj_start = self._random_date(prog_start, max_start_date)
            proj_end = proj_start + timedelta(days=project_duration_days)

        duration_ratio = max(1.0, project_duration_days / 30.0)
        scaled_tasks = int(options['tasks'] * duration_ratio)
        scaled_users = max(1, int(options['users'] * duration_ratio))

        project_users = [fake.name()[:256] for _ in range(scaled_users)]
        project_responsavel = (
            self.rng.choice(project_users) if project_users else fake.name()[:256]
        )

        today = timezone.now().date()
        if proj_start > today:
            proj_status = STATUS_PLANEJAMENTO
        elif proj_end < today:
            proj_status = self.rng.choice(
                [STATUS_CONCLUIDO, STATUS_EM_ANDAMENTO, STATUS_SUSPENSO]
            )
        else:
            proj_status = self.rng.choice([STATUS_EM_ANDAMENTO, STATUS_SUSPENSO])

        projeto = DimProjeto.objects.create(
            codigo_projeto=uuid.uuid4().hex[:6].upper(),
            nome_projeto=fake.catch_phrase()[:256],
            programa=programa,
            responsavel=project_responsavel,
            custo_hora=round(self.rng.uniform(50.0, 300.0), 2),
            data_inicio=self._get_or_create_dim_data(proj_start),
            data_fim_prevista=self._get_or_create_dim_data(proj_end),
            status=proj_status,
            lead_time_dias=self.rng.randint(0, 10),
            is_atrasado=(proj_end < today and proj_status == STATUS_EM_ANDAMENTO),
        )

        counts = {
            'tarefas': 0,
            'fatos_tarefa': 0,
            'solicitacoes': 0,
            'pedidos': 0,
            'empenhos': 0,
        }

        self._generate_tarefas(
            projeto,
            proj_start,
            proj_end,
            proj_status,
            scaled_tasks,
            project_users,
            fake,
            counts,
        )
        self._generate_materiais_para_projeto(
            projeto,
            proj_start,
            proj_end,
            proj_status,
            duration_ratio,
            global_fornecedores,
            global_materiais,
            fake,
            counts,
            categorias_globais,
        )

        self.stdout.write(
            f'    -> Projeto "{projeto.nome_projeto[:30]}..." [ID: {projeto.codigo_projeto}] ({projeto.status}, {project_duration_days} dias): '
            f"{counts['tarefas']} Tarefas ({counts['fatos_tarefa']} fatos tarefa), {scaled_users} usuários, "
            f"{counts['solicitacoes']} Solic., {counts['pedidos']} Pedidos, {counts['empenhos']} Empenhos."
        )

    def _process_programa(
        self,
        options,
        fake,
        categorias_globais,
        global_fornecedores,
        global_materiais,
    ):
        prog_start = fake.date_time_between(start_date='-5y', end_date='-1y').date()
        prog_end = prog_start + timedelta(days=self.rng.randint(1095, 3650))

        programa = DimPrograma.objects.create(
            codigo_programa=uuid.uuid4().hex[:6].upper(),
            nome_programa=f"Programa {fake.company()} - {fake.catch_phrase().title()}"[
                :256
            ],
            gerente_programa=fake.name()[:256],
            gerente_tecnico=fake.name()[:256],
            data_inicio=self._get_or_create_dim_data(prog_start),
            data_fim_prevista=self._get_or_create_dim_data(prog_end),
            status=self.rng.choice([STATUS_EM_ANDAMENTO, STATUS_CONCLUIDO]),
        )

        for _ in range(options['projects']):
            self._process_projeto(
                programa,
                prog_start,
                prog_end,
                options,
                fake,
                categorias_globais,
                global_fornecedores,
                global_materiais,
            )

        return programa

    @transaction.atomic
    def handle(self, *args, **options):
        self.dim_data_cache = {}
        if options['seed'] is not None:
            self.rng.seed(options['seed'])

        if options['clear']:
            self._clear_database()

        global_start = time.time()
        self.stdout.write(self.style.SUCCESS('Iniciando seed dinâmico...'))
        fake = Faker('pt_BR')

        categorias_globais = CATEGORIAS_GLOBAIS

        total_projects = options['programs'] * options['projects']

        num_fornecedores_total = max(10, total_projects // 2)
        global_fornecedores = self._create_fornecedores(
            num_fornecedores_total, fake, categorias_globais
        )

        # Limite temporário enquanto não temos uma resposta do cliente
        num_materiais_total = 10  # max(50, total_projects * 10)
        global_materiais = self._create_materiais(
            num_materiais_total, fake, categorias_globais
        )

        for p_idx in range(options['programs']):
            programa = self._process_programa(
                options,
                fake,
                categorias_globais,
                global_fornecedores,
                global_materiais,
            )
            elapsed = time.time() - global_start
            self.stdout.write(
                f'  - [{p_idx+1}/{options["programs"]}] Programa "{programa.nome_programa}" [ID: {programa.codigo_programa}] gerado em {elapsed:.2f} segundos.'
            )

        final_elapsed = time.time() - global_start
        self.stdout.write(
            self.style.SUCCESS(
                f'Seed dinâmico concluído em {final_elapsed:.2f} segundos! '
                f'Criados {options["programs"]} programas, {options["projects"]} projetos por programa.'
            )
        )
