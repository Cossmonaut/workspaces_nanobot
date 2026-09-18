## 11. Skill `audit_formulation_strengthener`

Skill для аудиторов: принимает **текст отклонения** + **файлы ВНД** (`.pdf`/`.docx`/`.txt`),
возвращает **человекочитаемый отчёт** в строгом русском юридическом стиле.

**Акт НЕ передаётся** — только отклонение и ВНД.

### 11.1 Особенности (отличающие от других skills)

| Особенность | Значение |
|---|---|
| `tables` | `[]` (пустой — ВНД приходят файлами, не из БД) |
| `vector_indexes` | `[]` (пустой — без embeddings, map по чанкам через LLM) |
| Pipeline | `analyze → search (map → фильтр/top-K) → synthesize` |
| LLM-вызовы | `1 + N + 1` (N = число чанков ВНД) |
| Формат отчёта | `.md` / `.txt` / `.docx` (по умолчанию `.md`), **не JSON** |

### 11.2 Архитектурный контракт

Skill **разрешено**:

- ✅ Использовать `lib.services.llm_client.call_llm` (через тонкую обёртку `scripts/llm.py`).
- ✅ Использовать `lib.services.text_splitter.split_text` для чанкования ВНД.
- ✅ Использовать `lib.core.skill_config.{get_llm_config, get_cli_config, get_max_retries, get_chunking_config, get_tool_config}`.
- ✅ Импортировать `workspace.utils.office_files.extract_text` для извлечения текста.
- ✅ Импортировать `lib.utils.text_utils.sanitize_value` для JSON-safe нормализации.

Skill **запрещено** (дополнительно к общим правилам):

- ❌ Импортировать что-либо из `workspace.skills.*` (включая `legal_summarizer`, `audit_analyzer`) — skill полностью автономен.
- ❌ Хранить ВНД в PostgreSQL или DuckDB (ВНД приходят каждый раз заново).
- ❌ Создавать vector-индексы для ВНД.
- ❌ Использовать `audit_analyzer`-специфичные ресурсы (`audits_index`, `violations_index`).
- ❌ Возвращать JSON как пользовательский артефакт (только `.md`/`.txt`/`.docx`).
- ❌ Добавлять skill-specific ключи в `project.json::skills.<name>` — `SkillSettings(extra="forbid")`.
- ❌ Модифицировать `sys.path` где-либо кроме `scripts/cli.py` (единственная разрешённая точка bootstrap).

### 11.3 Pipeline

```
CLI: --violation "..." --vnd vnd1.pdf --vnd vnd2.docx --output report.md

analyze (1 LLM):
  violation → {normalized, key_concepts, severity, suggested_vnd_sections}

search (N LLM, map по чанкам → фильтр → top-K):
  для каждого чанка ВНД:
    chunk + violation → LLM → {relation_type, relevance_score, why_matches}
  filter: score < 0.3 → отбрасываем
  re-rank: top-10 по score, evidence_id F1..FN

synthesize (1 LLM):
  analyze_data + search_findings → LLM →
    {title, violation_summary, established_facts, deviation_analysis,
     vnd_citations[{evidence_id, excerpt, relation_explanation}],
     verdict, recommended_formulation}
  validate citations:
    - evidence_id в реестре
    - excerpt — подстрока text_excerpt находки (.strip() обеих, без whitespace-collapse)
    - relation_type — из находки (не из LLM)
  dropped → citations_dropped + строка в отчёте

render: Report JSON → markdown → опционально .docx
```

### 11.4 Регистрация

В `project.json`:

```json
{
  "skills": {
    "audit_formulation_strengthener": {
      "enabled": true,
      "tables": [],
      "vector_indexes": [],
      "cli":   { "default_mode": "all", "timeout_sec": 120, "max_retries": 3 },
      "llm":   { "max_tokens": 4096, "temperature": 0.1 },
      "chunking": { "chunk_size": 6000, "chunk_overlap": 400 },
      "execution": { "max_chunks_for_execution": 50 }
    }
  }
}
```

Skill-specific константы **в Python-коде** (не в JSON):

- `scripts/modes/search.py::TOP_K_CANDIDATES = 10`
- `scripts/modes/search.py::MIN_RELEVANCE_SCORE = 0.3`

### 11.5 Тесты

- Unit + contract + CLI тесты в `tests/`. Все LLM-фазы замоканы на границе
  `scripts.llm.chat_json/chat`.
- Архитектурные инварианты в `tests/test_architecture.py` (AST + plain string).
- `python -m pytest` из `workspace/skills/audit_formulation_strengthener/` — зелёный.

См. `workspace/skills/audit_formulation_strengthener/references/testing.md`.

### 11.6 Что НЕ делает

- ❌ Не хранит ВНД в БД (stateless).
- ❌ Не использует embeddings (map по чанкам через LLM).
- ❌ Не принимает акт — только отклонение.
- ❌ Не возвращает JSON как пользовательский артефакт.
- ❌ Не имеет таблиц и vector-индексов.
- ❌ Не импортирует другие скиллы.
- ❌ Не использует confirmation-меню / `--confirm` (флаг удалён).
