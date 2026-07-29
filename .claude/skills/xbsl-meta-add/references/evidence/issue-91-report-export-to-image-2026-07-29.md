# Runtime Evidence: Отчет.ЭкспортироватьВИзображение()

Date: 2026-07-29

Scope: issue #91, method-level compile/runtime smoke for
`Стд::Отчеты::Отчет.ЭкспортироватьВИзображение()`.

Source fact:

- `Отчет _ 1С_Предприятие.Элемент.pdf`
- Page title: `Отчет | 1С:Предприятие.Элемент`
- PDF created: 2026-07-29 17:24:28 MSK
- Documentation last updated: 2026-05-13
- Versioned URL:
  `https://1cmycloud.com/console/help/element/9.2/docs/stdlib/element/xbsl/Std/Reports/Report_ru/#%D1%8D%D0%BA%D1%81%D0%BF%D0%BE%D1%80%D1%82%D0%B8%D1%80%D0%BE%D0%B2%D0%B0%D1%82%D1%8C%D0%B2%D0%B8%D0%B7%D0%BE%D0%B1%D1%80%D0%B0%D0%B6%D0%B5%D0%BD%D0%B8%D0%B5`

Test app:

- application: `test-app`
- app-id: `019d5dbf-b908-7ee4-8f77-a331c4a51e6e`
- project-id: `019d5dbf-2c65-7c77-bd5a-b07e50cd3d77`
- technology-version: `9.2.9-12`
- URI: `https://app-458425730.1cmycloud.com/applications/test-app`

Safety:

- dump-id: `019fae4d-c2bf-7808-912d-dc421b40a6ea`
- dump status before deploy: `Ready`
- dump task: `ExportApplication 019fae4d-c45e-795f-a272-707cc90a92b0 Completed`

Temporary project:

- source directory: `/tmp/xbsl_issue91_runtime_20260729/Demo/TestApp`
- build file: `/tmp/xasm-build/TestApp 1.0-217.xasm`
- added files:
  - `/tmp/xbsl_issue91_runtime_20260729/Demo/TestApp/Отчёты/ЭкспортОтчетаSmoke.yaml`
  - `/tmp/xbsl_issue91_runtime_20260729/Demo/TestApp/Отчёты/ЭкспортОтчетаSmoke.xbsl`

Smoke module:

```xbsl
@ВПодсистеме
метод ПолучитьPng(ВыполненныйОтчет: Стд::Отчеты::Отчет): Байты
    возврат ВыполненныйОтчет.ЭкспортироватьВИзображение()
;
```

Deploy command:

```bash
{python} .claude/skills/xbsl-deploy/scripts/deploy.py \
  --project-dir /tmp/xbsl_issue91_runtime_20260729/Demo/TestApp \
  --app-id 019d5dbf-b908-7ee4-8f77-a331c4a51e6e \
  --project-id 019d5dbf-2c65-7c77-bd5a-b07e50cd3d77 \
  --version 1.0-217 \
  --branch issue-91-report-export-smoke \
  --commit issue-91-report-export-smoke \
  --commit-message issue-91-report-export-to-image-runtime-smoke
```

Deploy result:

```text
version: 1.0-217
image-id: 019fae4e-535b-757a-938c-f0df7c4c53d5
status after update: Running
```

Application task:

```text
UpdateApplicationConfiguration: 019fae4e-563a-7437-83a7-5d091c1db5b0 Completed
start-date: 2026-07-29T14:36:37.526Z
end-date: 2026-07-29T14:36:57.421Z
error-message: ""
```

Final app state:

```text
status: Running
technology-version: 9.2.9-12
source.project-version: 1.0-217
source.project-version-id: 019fae4e-535b-757a-938c-f0df7c4c53d5
error: null
```
