import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Project, RepoEdge, RepoFile, WorkItem
from app.runtime.dag import TaskScopeError, _change_surface, _payload_for_stage, _task_payload_from_summary, generate_template_dag


def test_task_payload_from_summary_carries_target_scope_and_budget():
    payload = _task_payload_from_summary(
        {
            "task_id": "task-123",
            "task_title": "Improve homepage layout",
            "goal": "Improve homepage layout",
            "target_files": ["index.html", "styles.css"],
            "edit_budget": {
                "mode": "minimal_patch",
                "max_files": 2,
                "hard_max_files": 4,
            },
        }
    )

    assert payload["target_files"] == ["index.html", "styles.css"]
    assert payload["files"] == ["index.html", "styles.css"]
    assert payload["expected_files"] == ["index.html", "styles.css"]
    assert payload["edit_budget"] == {
        "mode": "minimal_patch",
        "max_files": 2,
        "hard_max_files": 4,
    }


def test_task_payload_from_summary_infers_frontend_entrypoint_from_hero_goal():
    payload = _task_payload_from_summary(
        {
            "task_id": "task-hero",
            "task_title": "Implement hero section",
            "goal": "Implement hero section: Add a hero section to the homepage.",
        }
    )

    assert payload["expected_files"] == ["index.html"]


def test_task_payload_from_summary_ignores_sentence_artifact_file_hint():
    payload = _task_payload_from_summary(
        {
            "task_id": "task-footer",
            "task_title": "Enhance footer and main section",
            "goal": "Enhance footer and main section: Please work on main section and footer section make all sync in design so that it look nice overall..along with header",
            "task_description": "Please work on main section and footer section make all sync in design so that it look nice overall..along with header",
        }
    )

    assert payload["expected_files"] == ["index.html"]


def test_task_payload_from_summary_keeps_valid_text_file_hints():
    payload = _task_payload_from_summary(
        {
            "task_id": "task-hints",
            "task_title": "Polish layout",
            "goal": "Update index.html and test_index_html.py to reflect the new hero and footer.",
        }
    )

    assert payload["expected_files"] == ["index.html", "test_index_html.py"]


def test_payload_for_write_tests_targets_generated_test_file():
    payload = _payload_for_stage(
        "WRITE_TESTS",
        {
            "task_id": "task-hero",
            "task_title": "Implement hero section",
            "goal": "Implement hero section",
            "expected_files": ["index.html"],
        },
    )

    assert payload["related_files"] == ["index.html"]
    assert payload["target_files"] == ["test_index_html.py"]
    assert payload["expected_files"] == ["test_index_html.py"]
    assert payload["required"] is False
    assert payload["blocking"] is False


def test_payload_for_run_tests_is_optional_and_non_blocking():
    payload = _payload_for_stage(
        "RUN_TESTS",
        {
            "task_id": "task-api",
            "task_title": "Initialize backend",
            "goal": "Initialize backend",
            "expected_files": ["app.py"],
        },
    )

    assert payload["required"] is False
    assert payload["criticality"] == "OPTIONAL"
    assert payload["blocking"] is False


def test_payload_for_review_stages_is_non_blocking():
    review_diff = _payload_for_stage(
        "REVIEW_DIFF",
        {
            "task_id": "task-review",
            "task_title": "Review backend",
            "goal": "Review backend",
            "expected_files": ["app.py"],
        },
    )
    review_integration = _payload_for_stage(
        "REVIEW_INTEGRATION",
        {
            "task_id": "task-review",
            "task_title": "Review backend",
            "goal": "Review backend",
            "expected_files": ["app.py"],
        },
    )

    assert review_diff["required"] is False
    assert review_diff["blocking"] is False
    assert review_integration["required"] is False
    assert review_integration["blocking"] is False


def test_payload_for_code_frontend_prefers_project_intent_monorepo_root():
    payload = _payload_for_stage(
        "CODE_FRONTEND",
        {
            "task_id": "task-ui",
            "task_title": "Implement hero section",
            "goal": "Implement hero section with CTA",
            "project_intent": {
                "repo_layout": "monorepo",
                "frontend_stack": "vue_vite",
                "architecture_mode": "guided",
            },
        },
    )

    assert payload["package_affinity"] == "apps/web"
    assert any(str(path).startswith("apps/web/") for path in payload.get("target_files", []))


def test_payload_for_code_frontend_polish_sets_polish_mutation_contract():
    payload = _payload_for_stage(
        "CODE_FRONTEND",
        {
            "task_id": "task-polish",
            "task_title": "Polish landing page",
            "goal": "Polish landing page typography and spacing for responsiveness",
            "expected_files": ["apps/web/src/pages/LandingPage.vue"],
        },
    )

    assert payload["mutation_class"] == "POLISH"
    assert payload["allowed_operations"] == ["note", "apply_patch"]
    assert "replace_landing_page" in payload["forbidden_operations"]
    assert payload["zone_composer_required"] is True
    assert "apps/web/src/pages/LandingPage.vue" in payload["protected_files"]


def test_payload_for_genesis_foundation_sets_foundation_mutation_contract():
    payload = _payload_for_stage(
        "GENESIS_FOUNDATION",
        {
            "task_id": "task-foundation",
            "task_title": "Genesis foundation",
            "goal": "Initialize shell and primitives",
            "task_source": "genesis_setup",
        },
    )

    assert payload["mutation_class"] == "FOUNDATION"
    assert "apps/web/src/App.vue" in payload["protected_files"]
    assert "hero" in payload["allowed_zones"]


def test_payload_for_plan_dag_allows_note_operations():
    payload = _payload_for_stage(
        "PLAN_DAG",
        {
            "task_id": "task-plan",
            "task_title": "Hero section",
            "goal": "Implement hero section on landing page",
            "expected_files": ["apps/web/src/components/landing/HeroSection.vue"],
        },
    )
    assert payload["mutation_class"] == "FEATURE"
    assert "note" in payload["allowed_operations"]


def test_payload_for_code_frontend_add_section_prefers_feature_over_polish():
    payload = _payload_for_stage(
        "CODE_FRONTEND",
        {
            "task_id": "task-testimonials",
            "task_title": "Add Testimonials Section",
            "goal": "Create a new reusable testimonials section component for the landing page.",
            "task_description": "Create component and integrate into landing page zone.",
            "expected_files": [
                "apps/web/src/components/landing/TestimonialsSection.vue",
                "apps/web/src/pages/LandingPage.vue",
            ],
        },
    )
    assert payload["mutation_class"] == "FEATURE"


def test_payload_for_code_backend_prefers_project_intent_monorepo_root():
    payload = _payload_for_stage(
        "CODE_BACKEND",
        {
            "task_id": "task-api",
            "task_title": "Add lead submission endpoint",
            "goal": "Add lead submission endpoint",
            "project_intent": {
                "repo_layout": "monorepo",
                "backend_stack": "fastapi",
                "architecture_mode": "guided",
            },
        },
    )

    assert payload["package_affinity"] == "apps/api"
    assert any(str(path).startswith("apps/api/") for path in payload.get("target_files", []))


def test_payload_for_code_backend_uses_project_intent_capability_allowlist():
    payload = _payload_for_stage(
        "CODE_BACKEND",
        {
            "task_id": "task-intent-caps",
            "task_title": "Integrate auth and CRM sync",
            "goal": "Integrate auth and CRM sync for lead flow",
            "project_intent": {
                "repo_layout": "monorepo",
                "backend_stack": "fastapi",
                "capabilities": ["Auth", "CRM Sync", "Email"],
            },
            "expected_files": ["apps/api/app/main.py"],
        },
    )

    topology = payload.get("backend_topology_plan")
    assert isinstance(topology, dict)
    assert topology.get("allowed_capabilities") == ["auth_identity", "crm_sync", "notification_dispatch"]
    capability_modules = topology.get("capability_modules") or []
    assert any(str(path).endswith("auth_identity_binding.py") for path in capability_modules)
    assert any(str(path).endswith("crm_sync_binding.py") for path in capability_modules)


def test_backend_stage_payloads_keep_deterministic_package_layer_and_topology_affinity():
    seed = {
        "task_id": "task-backend-affinity",
        "task_title": "Integrate HubSpot sync",
        "goal": "Integrate hubspot sync and add lead submission endpoint",
        "project_intent": {
            "repo_layout": "monorepo",
            "backend_stack": "fastapi",
            "capabilities": ["CRM Sync", "Auth"],
        },
    }
    code_backend = _payload_for_stage("CODE_BACKEND", seed)
    route_payload = _payload_for_stage("GENERATE_ROUTE", code_backend)
    repository_payload = _payload_for_stage("GENERATE_REPOSITORY", code_backend)

    assert route_payload["package_affinity"] == "apps/api"
    assert route_payload["layer_affinity"] == "route"
    assert route_payload["topology_zone"] == "crm_sync"
    assert all(str(path).startswith("apps/api/") for path in route_payload["target_files"])
    assert any("/routes/" in str(path) for path in route_payload["target_files"])

    assert repository_payload["package_affinity"] == "apps/api"
    assert repository_payload["layer_affinity"] == "repository"
    assert repository_payload["topology_zone"] == "crm_sync"
    assert all(str(path).startswith("apps/api/") for path in repository_payload["target_files"])
    assert any("/repositories/" in str(path) for path in repository_payload["target_files"])


def test_change_surface_prefers_backend_intent_over_noisy_requirement_labels():
    assert _change_surface(
        _task_payload_from_summary(
            {
                "task_id": "task-form-backend",
                "task_title": "Build Form Submission Backend",
                "goal": "Build form submission backend and validation pipeline",
                "impact": "apps/web",
            }
        )
    ) == "backend"
    assert _change_surface(
        _task_payload_from_summary(
            {
                "task_id": "task-crm",
                "task_title": "Integrate CRM System",
                "goal": "Integrate CRM system and sync captured leads to provider",
                "impact": "apps/web",
            }
        )
    ) == "backend"


@pytest.mark.anyio
async def test_generate_template_dag_omits_backend_for_frontend_scoped_task(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime-dag.db'}", future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Project.metadata.create_all)

    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    try:
        async with session_factory() as session:
            session.add(Project(id=project_id, name="Portfolio", tenant_id=tenant_id))
            await session.flush()

            created = await generate_template_dag(
                session,
                project_id,
                run_id,
                executor="codex",
                tenant_id=tenant_id,
                run_summary={
                    "task_id": "task-hero",
                    "task_title": "Implement hero section",
                    "goal": "Implement hero section: Add a hero section to the homepage.",
                },
            )
            await session.commit()

            assert created == 9
            work_items = (
                await session.execute(
                    select(WorkItem).where(WorkItem.run_id == run_id).order_by(WorkItem.priority.desc(), WorkItem.created_at.asc())
                )
            ).scalars().all()
            keys = [item.key for item in work_items]

            assert "CODE_BACKEND" not in keys
            assert keys == [
                "PLAN_DAG",
                "FOUNDATION_VALIDATE",
                "CODE_FRONTEND",
                "FRAMEWORK_VALIDATE",
                "WRITE_TESTS",
                "REVIEW_DIFF",
                "RUN_TESTS",
                "PREVIEW_VALIDATE",
                "REVIEW_INTEGRATION",
            ]

            frontend = next(item for item in work_items if item.key == "CODE_FRONTEND")
            write_tests = next(item for item in work_items if item.key == "WRITE_TESTS")
            run_tests = next(item for item in work_items if item.key == "RUN_TESTS")
            preview_validate = next(item for item in work_items if item.key == "PREVIEW_VALIDATE")

            assert frontend.payload["target_files"] == ["index.html"]
            assert write_tests.payload["target_files"] == ["test_index_html.py"]
            assert write_tests.payload["related_files"] == ["index.html"]
            assert run_tests.payload["target_files"] == ["test_index_html.py"]
            assert preview_validate.payload["blocking"] is False
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_generate_template_dag_includes_genesis_foundation_for_genesis_frontend(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime-dag-genesis.db'}", future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Project.metadata.create_all)

    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    try:
        async with session_factory() as session:
            session.add(Project(id=project_id, name="Genesis Frontend", tenant_id=tenant_id))
            await session.flush()

            created = await generate_template_dag(
                session,
                project_id,
                run_id,
                executor="codex",
                tenant_id=tenant_id,
                run_summary={
                    "task_id": "task-genesis-foundation",
                    "task_title": "Bootstrap frontend foundation",
                    "goal": "Create initial landing shell for new project.",
                    "task_source": "genesis_setup",
                    "repository_state": "GENESIS",
                },
            )
            await session.commit()

            assert created == 10
            work_items = (
                await session.execute(
                    select(WorkItem).where(WorkItem.run_id == run_id).order_by(WorkItem.priority.desc(), WorkItem.created_at.asc())
                )
            ).scalars().all()
            keys = [item.key for item in work_items]
            assert keys == [
                "PLAN_DAG",
                "GENESIS_FOUNDATION",
                "FOUNDATION_VALIDATE",
                "CODE_FRONTEND",
                "FRAMEWORK_VALIDATE",
                "WRITE_TESTS",
                "REVIEW_DIFF",
                "RUN_TESTS",
                "PREVIEW_VALIDATE",
                "REVIEW_INTEGRATION",
            ]

            genesis = next(item for item in work_items if item.key == "GENESIS_FOUNDATION")
            assert genesis.payload["target_files"] == [
                "apps/web/src/App.vue",
                "apps/web/src/layouts/PageShell.vue",
                "apps/web/src/components/layout/Navbar.vue",
                "apps/web/src/components/layout/Footer.vue",
                "apps/web/src/components/layout/MobileNav.vue",
                "apps/web/src/components/ui/SectionContainer.vue",
                "apps/web/src/components/ui/ContentGrid.vue",
                "apps/web/src/components/ui/Stack.vue",
                "apps/web/src/components/ui/SectionHeading.vue",
                "apps/web/src/components/ui/PrimaryButton.vue",
                "apps/web/src/components/zones/HeroZone.vue",
                "apps/web/src/components/zones/FeatureZone.vue",
                "apps/web/src/components/zones/TestimonialsZone.vue",
                "apps/web/src/components/zones/CTAZone.vue",
                "apps/web/src/pages/LandingPage.vue",
                "runtime-contracts/component-manifest.json",
                "runtime-contracts/topology_hash.json",
            ]
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_generate_template_dag_applies_fallback_scope_for_task_runs_without_file_scope(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime-dag-empty-scope.db'}", future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Project.metadata.create_all)

    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    try:
        async with session_factory() as session:
            session.add(Project(id=project_id, name="Scope-less project", tenant_id=tenant_id))
            await session.flush()

            created = await generate_template_dag(
                session,
                project_id,
                run_id,
                executor="codex",
                tenant_id=tenant_id,
                run_summary={
                    "task_id": "task-noscope",
                    "task_title": "Implement backend",
                    "goal": "Implement backend",
                },
            )
            assert created > 0
            items = (
                await session.execute(select(WorkItem).where(WorkItem.run_id == run_id).order_by(WorkItem.priority))
            ).scalars().all()
            backend_candidates = [
                item
                for item in items
                if item.key in {"GENERATE_ROUTE", "GENERATE_SERVICE", "GENERATE_REPOSITORY", "GENERATE_CAPABILITY_BINDING"}
            ]
            assert backend_candidates
            assert any((item.payload or {}).get("target_files") == ["app.py"] for item in backend_candidates)
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_generate_template_dag_reuses_indexed_frontend_component_and_page_neighbor(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime-dag-repo-index-frontend.db'}", future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Project.metadata.create_all)

    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    try:
        async with session_factory() as session:
            session.add(Project(id=project_id, name="Indexed frontend project", tenant_id=tenant_id))
            await session.flush()

            hero = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/web/src/components/landing/HeroSection.vue",
                language="ts",
                kind="ui_component",
                summary="Hero section for landing page CTA",
                features=["hero", "landing", "cta"],
            )
            page = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/web/src/pages/LandingPage.vue",
                language="ts",
                kind="ui_component",
                summary="Landing page composition shell",
                features=["landing", "page"],
            )
            session.add_all([hero, page])
            await session.flush()
            session.add(
                RepoEdge(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    source_file_id=hero.id,
                    target_file_id=page.id,
                    relation_type="import",
                )
            )
            await session.flush()

            await generate_template_dag(
                session,
                project_id,
                run_id,
                executor="codex",
                tenant_id=tenant_id,
                run_summary={
                    "task_id": "task-hero-indexed",
                    "task_title": "Implement hero section",
                    "goal": "Implement hero section with CTA for landing page",
                    "project_intent": {"repo_layout": "monorepo", "frontend_stack": "vue_vite"},
                },
            )

            frontend = await session.scalar(select(WorkItem).where(WorkItem.run_id == run_id, WorkItem.key == "CODE_FRONTEND"))
            assert frontend is not None
            assert frontend.payload["targeting_strategy"] == "repo_graph_neighbor_expansion"
            assert frontend.payload["component_reuse_preferred"] is True
            assert "apps/web/src/components/landing/HeroSection.vue" in frontend.payload["target_files"]
            assert "apps/web/src/pages/LandingPage.vue" in frontend.payload["related_files"]
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_generate_template_dag_prefers_exact_frontend_component_match_over_adjacent_neighbor(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime-dag-exact-frontend-match.db'}", future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Project.metadata.create_all)

    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    try:
        async with session_factory() as session:
            session.add(Project(id=project_id, name="Exact frontend match project", tenant_id=tenant_id))
            await session.flush()

            hero = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/web/src/components/landing/HeroSection.vue",
                language="ts",
                kind="ui_component",
                summary="Hero section for landing page CTA",
                features=["hero", "landing", "cta"],
            )
            cta = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/web/src/components/landing/CTASection.vue",
                language="ts",
                kind="ui_component",
                summary="Primary call to action section",
                features=["cta", "landing", "conversion"],
            )
            page = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/web/src/pages/LandingPage.vue",
                language="ts",
                kind="ui_component",
                summary="Landing page composition shell",
                features=["landing", "page"],
            )
            session.add_all([hero, cta, page])
            await session.flush()
            session.add_all(
                [
                    RepoEdge(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        source_file_id=hero.id,
                        target_file_id=page.id,
                        relation_type="import",
                    ),
                    RepoEdge(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        source_file_id=cta.id,
                        target_file_id=page.id,
                        relation_type="import",
                    ),
                ]
            )
            await session.flush()

            await generate_template_dag(
                session,
                project_id,
                run_id,
                executor="codex",
                tenant_id=tenant_id,
                run_summary={
                    "task_id": "task-cta-exact",
                    "task_title": "Add CTA Actions",
                    "goal": "Add CTA actions and conversion prompts on landing page",
                    "project_intent": {"repo_layout": "monorepo", "frontend_stack": "vue_vite"},
                },
            )

            frontend = await session.scalar(select(WorkItem).where(WorkItem.run_id == run_id, WorkItem.key == "CODE_FRONTEND"))
            assert frontend is not None
            selected_existing = (frontend.payload.get("targeting_evidence") or {}).get("selected_existing_files") or []
            assert selected_existing[0].endswith("CTASection.vue")
            reason_map = (frontend.payload.get("targeting_evidence") or {}).get("selected_existing_reason_map") or {}
            assert "apps/web/src/components/landing/CTASection.vue" in reason_map
            assert any(
                str(reason) in {"explicit_scope", "semantic:cta", "identity:cta"}
                for reason in reason_map["apps/web/src/components/landing/CTASection.vue"]
            )
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_generate_template_dag_reuses_indexed_backend_module_scope(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime-dag-repo-index-backend.db'}", future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Project.metadata.create_all)

    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    try:
        async with session_factory() as session:
            session.add(Project(id=project_id, name="Indexed backend project", tenant_id=tenant_id))
            await session.flush()

            service = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/api/app/services/lead_capture_service.py",
                language="py",
                kind="service_module",
                summary="Lead capture orchestration service",
                features=["lead", "capture", "crm_sync"],
            )
            repository = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/api/app/repositories/lead_repository.py",
                language="py",
                kind="repository_module",
                summary="Lead persistence repository",
                features=["lead", "storage"],
            )
            session.add_all([service, repository])
            await session.flush()

            await generate_template_dag(
                session,
                project_id,
                run_id,
                executor="codex",
                tenant_id=tenant_id,
                run_summary={
                    "task_id": "task-lead-indexed",
                    "task_title": "Add lead submission endpoint",
                    "goal": "Add lead submission endpoint and CRM sync",
                    "project_intent": {"repo_layout": "monorepo", "backend_stack": "fastapi"},
                },
            )

            backend = await session.scalar(select(WorkItem).where(WorkItem.run_id == run_id, WorkItem.key == "GENERATE_SERVICE"))
            assert backend is not None
            assert backend.payload["targeting_strategy"] == "repo_index_reuse"
            assert backend.payload["module_reuse_preferred"] is True
            assert "apps/api/app/services/lead_capture_service.py" in backend.payload["target_files"]
            evidence = backend.payload["targeting_evidence"]
            assert evidence["repo_index_used"] is True
            assert "apps/api/app/services/lead_capture_service.py" in evidence["selected_existing_files"]
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_generate_template_dag_prefers_exact_backend_module_match_over_adjacent_neighbor(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime-dag-exact-backend-match.db'}", future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Project.metadata.create_all)

    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    try:
        async with session_factory() as session:
            session.add(Project(id=project_id, name="Exact backend match project", tenant_id=tenant_id))
            await session.flush()

            analytics = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/api/app/services/analytics_tracking_service.py",
                language="py",
                kind="service_module",
                summary="Analytics event tracking service",
                features=["analytics", "tracking", "events"],
            )
            lead = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/api/app/services/lead_capture_service.py",
                language="py",
                kind="service_module",
                summary="Lead capture orchestration service",
                features=["lead", "capture", "submission"],
            )
            session.add_all([analytics, lead])
            await session.flush()

            await generate_template_dag(
                session,
                project_id,
                run_id,
                executor="codex",
                tenant_id=tenant_id,
                run_summary={
                    "task_id": "task-analytics-exact",
                    "task_title": "Add Analytics Event Tracking",
                    "goal": "Add analytics event tracking for CTA and lead form events",
                    "project_intent": {"repo_layout": "monorepo", "backend_stack": "fastapi"},
                },
            )

            backend = await session.scalar(select(WorkItem).where(WorkItem.run_id == run_id, WorkItem.key == "GENERATE_SERVICE"))
            assert backend is not None
            selected_existing = (backend.payload.get("targeting_evidence") or {}).get("selected_existing_files") or []
            assert selected_existing[0].endswith("analytics_tracking_service.py")
            reason_map = (backend.payload.get("targeting_evidence") or {}).get("selected_existing_reason_map") or {}
            assert "apps/api/app/services/analytics_tracking_service.py" in reason_map
            assert any(
                str(reason) in {"explicit_scope", "semantic:analytics", "identity:analytics"}
                for reason in reason_map["apps/api/app/services/analytics_tracking_service.py"]
            )
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_generate_template_dag_repeated_evolution_benchmark_preserves_affinity_and_reuse(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime-dag-repeated-evolution.db'}", future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Project.metadata.create_all)

    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    try:
        async with session_factory() as session:
            session.add(Project(id=project_id, name="Repeated evolution project", tenant_id=tenant_id))
            await session.flush()

            landing_page = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/web/src/pages/LandingPage.vue",
                language="ts",
                kind="ui_component",
                summary="Landing page composition shell",
                features=["landing", "page"],
            )
            hero_section = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/web/src/components/landing/HeroSection.vue",
                language="ts",
                kind="ui_component",
                summary="Hero section for landing page CTA",
                features=["hero", "landing", "cta"],
            )
            pricing_section = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/web/src/components/landing/PricingSection.vue",
                language="ts",
                kind="ui_component",
                summary="Pricing section for landing page plans",
                features=["pricing", "landing", "plans"],
            )
            cta_section = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/web/src/components/landing/CTASection.vue",
                language="ts",
                kind="ui_component",
                summary="Primary call to action section",
                features=["cta", "landing", "conversion"],
            )
            lead_capture_form = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/web/src/components/forms/LeadCaptureForm.vue",
                language="ts",
                kind="ui_component",
                summary="Lead capture form component",
                features=["lead", "capture", "form"],
            )
            admin_dashboard = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/web/src/pages/AdminDashboard.vue",
                language="ts",
                kind="ui_component",
                summary="Admin dashboard shell",
                features=["admin", "dashboard", "analytics"],
            )
            dashboard_sidebar = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/web/src/components/dashboard/DashboardSidebar.vue",
                language="ts",
                kind="ui_component",
                summary="Dashboard navigation sidebar",
                features=["dashboard", "admin", "navigation"],
            )
            lead_service = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/api/app/services/lead_capture_service.py",
                language="py",
                kind="service_module",
                summary="Lead capture orchestration service",
                features=["lead", "capture", "submission"],
            )
            analytics_service = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/api/app/services/analytics_tracking_service.py",
                language="py",
                kind="service_module",
                summary="Analytics event tracking service",
                features=["analytics", "tracking", "events"],
            )
            auth_service = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/api/app/services/auth_identity_service.py",
                language="py",
                kind="service_module",
                summary="Authentication and identity orchestration service",
                features=["auth", "identity", "session"],
            )
            crm_service = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/api/app/services/crm_sync_service.py",
                language="py",
                kind="service_module",
                summary="CRM synchronization orchestration service",
                features=["crm", "sync", "lead"],
            )
            webhook_service = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/api/app/services/webhook_retry_service.py",
                language="py",
                kind="service_module",
                summary="Webhook retry and replay orchestration service",
                features=["webhook", "retry", "integration"],
            )
            lead_repository = RepoFile(
                tenant_id=tenant_id,
                project_id=project_id,
                path="apps/api/app/repositories/lead_repository.py",
                language="py",
                kind="repository_module",
                summary="Lead persistence repository",
                features=["lead", "storage"],
            )
            session.add_all(
                [
                    landing_page,
                    hero_section,
                    pricing_section,
                    cta_section,
                    lead_capture_form,
                    admin_dashboard,
                    dashboard_sidebar,
                    lead_service,
                    analytics_service,
                    auth_service,
                    crm_service,
                    webhook_service,
                    lead_repository,
                ]
            )
            await session.flush()
            session.add_all(
                [
                    RepoEdge(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        source_file_id=hero_section.id,
                        target_file_id=landing_page.id,
                        relation_type="import",
                    ),
                    RepoEdge(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        source_file_id=pricing_section.id,
                        target_file_id=landing_page.id,
                        relation_type="import",
                    ),
                    RepoEdge(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        source_file_id=cta_section.id,
                        target_file_id=landing_page.id,
                        relation_type="import",
                    ),
                    RepoEdge(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        source_file_id=lead_capture_form.id,
                        target_file_id=landing_page.id,
                        relation_type="import",
                    ),
                    RepoEdge(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        source_file_id=dashboard_sidebar.id,
                        target_file_id=admin_dashboard.id,
                        relation_type="import",
                    ),
                ]
            )
            await session.flush()

            runs = [
                (
                    uuid.uuid4(),
                    {
                        "task_id": "task-hero-reuse",
                        "task_title": "Add Hero Section",
                        "goal": "Add hero section to the landing page",
                        "project_intent": {"repo_layout": "monorepo", "frontend_stack": "vue_vite"},
                    },
                    "CODE_FRONTEND",
                    "apps/web",
                    ("HeroSection.vue",),
                    "apps/web/src/pages/LandingPage.vue",
                    True,
                ),
                (
                    uuid.uuid4(),
                    {
                        "task_id": "task-pricing-reuse",
                        "task_title": "Add Pricing Section",
                        "goal": "Add pricing section with plans on landing page",
                        "project_intent": {"repo_layout": "monorepo", "frontend_stack": "vue_vite"},
                    },
                    "CODE_FRONTEND",
                    "apps/web",
                    ("PricingSection.vue",),
                    "apps/web/src/pages/LandingPage.vue",
                    True,
                ),
                (
                    uuid.uuid4(),
                    {
                        "task_id": "task-testimonials-create",
                        "task_title": "Add Testimonials Section",
                        "goal": "Add testimonials section to the landing page",
                        "project_intent": {"repo_layout": "monorepo", "frontend_stack": "vue_vite"},
                    },
                    "CODE_FRONTEND",
                    "apps/web",
                    ("TestimonialsSection.vue",),
                    "apps/web/src/pages/LandingPage.vue",
                    False,
                ),
                (
                    uuid.uuid4(),
                    {
                        "task_id": "task-lead-form-reuse",
                        "task_title": "Add Lead Capture Form",
                        "goal": "Add lead capture form on landing page with validation",
                        "project_intent": {"repo_layout": "monorepo", "frontend_stack": "vue_vite"},
                    },
                    "CODE_FRONTEND",
                    "apps/web",
                    ("LeadCaptureForm.vue",),
                    "apps/web/src/pages/LandingPage.vue",
                    True,
                ),
                (
                    uuid.uuid4(),
                    {
                        "task_id": "task-cta-reuse",
                        "task_title": "Add CTA Actions",
                        "goal": "Add CTA actions and conversion prompts on landing page",
                        "project_intent": {"repo_layout": "monorepo", "frontend_stack": "vue_vite"},
                    },
                    "CODE_FRONTEND",
                    "apps/web",
                    ("CTASection.vue",),
                    "apps/web/src/pages/LandingPage.vue",
                    True,
                ),
                (
                    uuid.uuid4(),
                    {
                        "task_id": "task-analytics-reuse",
                        "task_title": "Add Analytics Event Tracking",
                        "goal": "Add analytics event tracking for CTA and lead form events",
                        "project_intent": {"repo_layout": "monorepo", "backend_stack": "fastapi"},
                    },
                    "GENERATE_SERVICE",
                    "apps/api",
                    "analytics_tracking_service.py",
                    None,
                    True,
                ),
                (
                    uuid.uuid4(),
                    {
                        "task_id": "task-utm-create",
                        "task_title": "Add UTM Tracking",
                        "goal": "Add UTM tracking in backend API for attribution capture",
                        "project_intent": {"repo_layout": "monorepo", "backend_stack": "fastapi"},
                    },
                    "GENERATE_SERVICE",
                    "apps/api",
                    "utm_tracking_service.py",
                    None,
                    False,
                ),
                (
                    uuid.uuid4(),
                    {
                        "task_id": "task-form-backend-create",
                        "task_title": "Build Form Submission Backend",
                        "goal": "Build form submission backend with request validation and persistence",
                        "impact": "apps/web",
                        "project_intent": {"repo_layout": "monorepo", "backend_stack": "fastapi"},
                    },
                    "GENERATE_SERVICE",
                    "apps/api",
                    "form_submission_service.py",
                    None,
                    False,
                ),
                (
                    uuid.uuid4(),
                    {
                        "task_id": "task-crm-reuse",
                        "task_title": "Integrate CRM System",
                        "goal": "Integrate CRM system and sync captured leads to provider",
                        "project_intent": {"repo_layout": "monorepo", "backend_stack": "fastapi"},
                    },
                    "GENERATE_SERVICE",
                    "apps/api",
                    "crm_sync_service.py",
                    None,
                    True,
                ),
                (
                    uuid.uuid4(),
                    {
                        "task_id": "task-dashboard-reuse",
                        "task_title": "Develop Admin Dashboard",
                        "goal": "Develop admin dashboard with navigation and analytics widgets",
                        "project_intent": {"repo_layout": "monorepo", "frontend_stack": "vue_vite"},
                    },
                    "CODE_FRONTEND",
                    "apps/web",
                    "AdminDashboard.vue",
                    None,
                    True,
                ),
            ]

            frontend_runs = 0
            backend_runs = 0
            for run_id, summary, stage_key, expected_package, expected_file_name, expected_related, should_reuse_existing in runs:
                created = await generate_template_dag(
                    session,
                    project_id,
                    run_id,
                    executor="codex",
                    tenant_id=tenant_id,
                    run_summary=summary,
                )
                assert created > 0
                item = await session.scalar(select(WorkItem).where(WorkItem.run_id == run_id, WorkItem.key == stage_key))
                assert item is not None
                preview_validate = await session.scalar(
                    select(WorkItem).where(WorkItem.run_id == run_id, WorkItem.key == "PREVIEW_VALIDATE")
                )
                assert preview_validate is not None
                assert (preview_validate.payload or {}).get("blocking") is False

                payload = item.payload or {}
                evidence = payload.get("targeting_evidence") or {}
                target_files = [str(path) for path in payload.get("target_files") or []]
                expected_files = [str(path) for path in payload.get("expected_files") or []]
                related_files = [str(path) for path in payload.get("related_files") or []]
                selected_existing = [str(path) for path in evidence.get("selected_existing_files") or []]

                assert payload["package_affinity"] == expected_package
                assert payload["targeting_strategy"] in {"repo_index_reuse", "repo_graph_neighbor_expansion"}
                assert evidence.get("repo_index_used") is True
                assert any(path.startswith(f"{expected_package}/") for path in target_files)
                expected_file_names = expected_file_name if isinstance(expected_file_name, tuple) else (expected_file_name,)
                assert any(any(candidate in path for candidate in expected_file_names) for path in [*target_files, *expected_files])

                if expected_package == "apps/web":
                    frontend_runs += 1
                    assert payload["component_reuse_preferred"] is True
                    if expected_related:
                        assert expected_related in related_files or expected_related in target_files or expected_related in expected_files
                    assert all(path.startswith("apps/web/") for path in target_files)
                else:
                    backend_runs += 1
                    assert payload["module_reuse_preferred"] is True
                    assert all(path.startswith("apps/api/") for path in target_files)
                if should_reuse_existing:
                    assert any(any(candidate in path for candidate in expected_file_names) for path in selected_existing)
                else:
                    assert not any(any(candidate in path for candidate in expected_file_names) for path in selected_existing)
            assert frontend_runs == 6
            assert backend_runs == 4
    finally:
        await engine.dispose()
