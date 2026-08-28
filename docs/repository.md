# Complete Repository Structure

```

bioresearch-ai/
│
├── app/
│   ├── api/
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── health.py
│   │   │   ├── papers.py
│   │   │   ├── report.py
│   │   │   ├── search.py
│   │   │   ├── workspace.py
│   │   │   └── __init__.py
│   │   │
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── report_request.py
│   │   │   ├── report_response.py
│   │   │   ├── search_request.py
│   │   │   ├── search_response.py
│   │   │   ├── workspace_request.py
│   │   │   └── workspace_response.py
│   │   │      
│   │   └── __init__.py
│   │
│   ├── application/
│   │   ├── agents
│   │   ├── prompts
│   │   │   ├── __init__.py
│   │   │   └── comparison_prompt
│   │   │
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── research_assistant.py
│   │   │   └── workspace_service
│   │   │
│   │   ├── use_cases/
│   │   │   ├── __init__.py
│   │   │   ├── create_workspace.py
│   │   │   ├── generate_report.py
│   │   │   ├── get_paper.py
│   │   │   ├── get_workspace.py
│   │   │   ├── search_literature.py
│   │   │   ├── summarize_papers.py
│   │   │   └── update_workspace.py
│   │   │   
│   │   └── workflows/
│   │   
│   ├── config/
│   │   ├── __init__.py
│   │   ├── database.py
│   │   ├── container.py
│   │   ├── llm.py
│   │   ├── logging.py
│   │   ├── pubmed.py
│   │   └── settings.py
│   │
│   ├── core/
│   │   ├── enums/
│   │   │   ├── __init__.py
│   │   │   ├── citation_style.py
│   │   │   ├── environment.py
│   │   │   ├── llm_provider.py
│   │   │   ├── log_level.py
│   │   │   ├── report_format.py
│   │   │   └── search_source.py
│   │   │
│   │   ├── __init__.py
│   │   ├── exceptions.py
│   │   └── logger.py
│   │   
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── entities/
│   │   │   ├── author.py
│   │   │   ├── citation.py
│   │   │   ├── journal.py
│   │   │   ├── paper.py
│   │   │   ├── research_question.py
│   │   │   ├── research_report.py
│   │   │   ├── research_session.py
│   │   │   └── summary.py
│   │   │   
│   │   ├── interfaces/
│   │   │   ├── __init__.py
│   │   │   ├── knowledge_base.py
│   │   │   ├── literature_searcher.py
│   │   │   ├── llm_provider.py
│   │   │   ├── report_generator.py
│   │   │   └── workspace_repositiory.py
│   │   │   
│   │   └── models/
│   │       ├── __init__.py
│   │       ├── llm_response.py
│   │       └── prompt.py
│   │
│   ├── infrastructure/
│   │   ├── pubmed/
│   │   │   ├── __init__.py
│   │   │   ├── client.py
│   │   │   ├── mapper.py
│   │   │   └── provider.py
│   │   │
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   ├── alibaba_provider.py
│   │   │   ├── anthropic_provider.py
│   │   │   ├── azure_openai_provider.py
│   │   │   ├── baichuan_provider.py
│   │   │   ├── baidu_provider.py
│   │   │   ├── base_provider.py
│   │   │   ├── bytedance_provider.py
│   │   │   ├── deepseek_provider.py
│   │   │   ├── genimi_provider.py
│   │   │   ├── hauwei_provider.py
│   │   │   ├── llm_factory.py
│   │   │   ├── minimax_provider.py
│   │   │   ├── moonshot_provider.py
│   │   │   ├── ollama_provider.py
│   │   │   ├── openai_provider.py
│   │   │   ├── report_generator.py
│   │   │   ├── report_mapper.py
│   │   │   ├── sensetime_provider.py
│   │   │   ├── step_fun_provider.py
│   │   │   ├── tencent_provider.py
│   │   │   ├── yi_provider.py
│   │   │   └── zhipu_provider.py
│   │   │
│   │   ├── storage/
│   │   │   ├── __init__.py
│   │   │   └── sqlite_workspace_repository.py
│   │   │
│   │   ├── mcp/
│   │   └── a2a/
│   │
│   ├── presentation/
│   │   ├── components/
│   │   │   ├── __init__.py
│   │   │   ├── question_input.py
│   │   │   ├── paper_list.py
│   │   │   ├── paper_card.py
│   │   │   ├── evidence_panel.py
│   │   │   ├── report_panel.py
│   │   │   ├── references_panel.py
│   │   │   ├── status_bar.py
│   │   │   └── navigation.py
│   │   │       
│   │   ├── pages/
│   │   │   ├── __init__.py
│   │   │   ├── home.py
│   │   │   ├── workspace.py
│   │   │   └── report.py
│   │   │
│   │   ├── state/
│   │   │   ├── __init__.py
│   │   │   └── workspace_state.py
│   │   │
│   │   ├── view_models/
│   │   │   ├── __init__.py
│   │   │   └── workspace_view_model.py
│   │   │
│   │   └── __init__.py
│   │
│   ├── tools/
│   │
│   └── __init__.py
│
├── docs/
│   ├── adr/
│   │   ├── ADR-001-adopt-clean-architecture.md
│   │   └── README.md
│   │
│   ├── architecture.md
│   └── repository.md
│
├── frontend/
│   ├── public/
│   │   └── favicon.ico
│   │
│   ├── src/
│   │   ├── api/
│   │   │   └── client.ts
│   │   │
│   │   ├── assets/
│   │   │
│   │   ├── components/
│   │   │   ├── Button.tsx
│   │   │   ├── EvidencePanel.tsx
│   │   │   ├── LiteratureSearch.tsx
│   │   │   ├── LoadingSpinner.tsx
│   │   │   ├── Navigation.tsx
│   │   │   ├── PaperCard.tsx
│   │   │   ├── PaperList.tsx
│   │   │   ├── QuestionInput.tsx
│   │   │   ├── ReferencesPanel.tsx
│   │   │   ├── ReportPanel.tsx
│   │   │   ├── StatusBar.tsx
│   │   │   └── ToastContainer.tsx
│   │   │
│   │   ├── pages/
│   │   │   ├── Home.tsx
│   │   │   ├── Report.tsx
│   │   │   └── Workspace.tsx
│   │   │
│   │   ├── state/
│   │   │   ├── toastStore.ts
│   │   │   └── workspaceStore.ts
│   │   │
│   │   ├── styles/
│   │   │   ├── nimations.css
│   │   │   ├── components.css
│   │   │   ├── globals.css
│   │   │   ├── index.css
│   │   │   ├── tailwind.css
│   │   │   ├── utilities.css
│   │   │   └── variables.css
│   │   │
│   │   ├── models/
│   │   │   ├── paper.ts
│   │   │   ├── report.ts
│   │   │   └── workspace.ts
│   │   │
│   │   ├── hooks/
│   │   │   └── useWorkspace.ts
│   │   │
│   │   ├── layouts/
│   │   │   └── MainLayout.tsx
│   │   │
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   └── router.tsx
│   │
│   ├── index.html
│   ├── package.json
│   ├── postcss.config.js
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   └── vite.config.ts
│   
├── examples/
├── notebooks/
├── scripts/
│   ├── setup.sh
│   └── start.py
│   
├── tests/
├── .env
├── .env.example
├── .gitignore
├── ARCHITECTURE.md
├── CHANGELOG
├── CONDE_OF_CONDUCT
├── CONTRIBUTING
├── LICENSE
├── main.py
├── README.md
├── requirements.txt
├── ROADMAP.md
└── SECURITY.md

```
