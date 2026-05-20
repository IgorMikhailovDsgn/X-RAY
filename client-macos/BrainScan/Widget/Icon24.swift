import AppKit

/// Иконки виджета. Источник — кастомные SVG в Assets.xcassets
/// ([Resources/Assets.xcassets/](../Resources/Assets.xcassets/)).
/// SF Symbols — fallback на случай если ассет не найден (или нет такого варианта).
enum Icon24: String, CaseIterable {
    case close
    case annotate
    case detect
    case settings
    case check
    case send

    /// Имя image set в asset catalog (для тех, у кого есть кастомный ассет).
    var assetName: String? {
        switch self {
        case .close: return "icon-close"
        case .annotate: return "icon-annotate"
        case .detect: return "icon-detect"
        case .settings: return "icon-settings"
        case .check, .send: return nil
        }
    }

    /// SF Symbol fallback — используется если ассета нет.
    var symbolName: String {
        switch self {
        case .close: return "xmark.circle.fill"
        case .annotate: return "text.bubble"
        case .detect: return "dot.viewfinder"
        case .settings: return "gearshape.fill"
        case .check: return "checkmark"
        case .send: return "paperplane.fill"
        }
    }

    var accessibilityLabel: String {
        switch self {
        case .close: return "Close"
        case .annotate: return "Annotate"
        case .detect: return "Detect"
        case .settings: return "Settings"
        case .check: return "Confirm"
        case .send: return "Send"
        }
    }

    /// Готовый template-image. AppKit перекрашивает под `contentTintColor`.
    /// pointSize контролирует размер SF-fallback'а; для asset-based иконок
    /// используется исходный размер из SVG.
    func makeImage(pointSize: CGFloat = 22) -> NSImage {
        if let assetName, let asset = NSImage(named: assetName) {
            asset.isTemplate = true
            return asset
        }
        let symbol = NSImage(
            systemSymbolName: symbolName,
            accessibilityDescription: accessibilityLabel
        )
        let image = symbol ?? NSImage(size: NSSize(width: pointSize, height: pointSize))
        let config = NSImage.SymbolConfiguration(pointSize: pointSize, weight: .regular)
        let configured = image.withSymbolConfiguration(config) ?? image
        configured.isTemplate = true
        return configured
    }
}
