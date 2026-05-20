# brainscan-client-macos

Нативный macOS-клиент BrainScan: Swift + SwiftUI, menubar-приложение, overlay-разметка.

## Текущий статус (Phase C step 1-2)

- Bootstrap Xcode-проекта через XcodeGen (`project.yml`)
- LSUIElement-приложение с базовым NSStatusItem menu (Annotate/Detect disabled, Sign-in placeholder)
- Keychain-обёртка + `TokenStore` для JWT-пар
- 10 unit-тестов через XCTest

UI-экраны (Sign-in, Default widget, Annotate overlay) — после получения макетов Figma.

## Сборка

```bash
brew install xcodegen        # один раз
cd client-macos
xcodegen generate            # создаёт BrainScan.xcodeproj из project.yml

# CLI-сборка (если xcode-select ещё указывает на CommandLineTools)
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  xcodebuild -project BrainScan.xcodeproj -scheme BrainScan -configuration Debug build

# Запуск тестов
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  xcodebuild -project BrainScan.xcodeproj -scheme BrainScan -destination 'platform=macOS' test

# Или просто: open BrainScan.xcodeproj
```

После сборки `.app` появится в `build/Build/Products/Debug/BrainScan.app` — менюбар-иконка с мозгом и меню «Annotate / Detect / Sign in / Quit».

## Запланированная структура

```
client-macos/
├── BrainScan.xcodeproj
├── BrainScan/
│   ├── BrainScanApp.swift          # LSUIElement=true в Info.plist
│   ├── Menubar/                    # NSStatusItem
│   ├── Widget/                     # Default State floating panel
│   ├── Overlay/                    # transparent NSWindow level=.screenSaver
│   │   ├── OverlayWindowController.swift
│   │   ├── BboxCanvasView.swift    # рисование/drag/resize bbox
│   │   ├── AnnotationStateMachine.swift  # Region/Tumor states, см. docs/
│   │   ├── ValidationEngine.swift  # min size, intersection, inside-region
│   │   └── CoordinateConverter.swift  # logical/physical/crop
│   ├── Capture/                    # ScreenCaptureKit, multi-monitor
│   ├── Auth/                       # login screen, Keychain wrapper
│   ├── Sync/                       # GRDB SQLite + sync_queue worker
│   ├── API/                        # URLSession client, JWT refresh
│   └── Models/                     # Codable DTO (из shared/openapi.yaml)
└── BrainScanTests/
```

## Зависимости (через Swift Package Manager в Xcode)

- **GRDB.swift** — SQLite-обёртка для sync_queue
- **KeychainAccess** (или нативный Security framework) — хранение JWT
- (опционально) **OpenAPIKit** или генерация DTO из `shared/openapi.yaml`

## Permissions

При первом запуске запрос **Screen Recording** через ScreenCaptureKit. Без него overlay не сможет получить замороженный скриншот. На unsigned dev-сборке: System Settings → Privacy & Security → Screen Recording → разрешить вручную.

## Полный UI-контракт

См. `docs/brainscan_annotation_mode.md` — все состояния Region/Tumor, каскадные правила, валидация, action mapping.
