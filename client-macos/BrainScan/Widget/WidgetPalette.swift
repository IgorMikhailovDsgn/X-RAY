import AppKit

/// Палитра виджета — спецификация от пользователя:
/// - Outer container: #02091A 90%, bg-blur 12, shadow Y8 blur 16.5
/// - Inner action container: #FFFFFF 4% fill, #FFFFFF 20% 1px inside stroke
/// - Item label: #FFFFFF 70% default / 100% active
/// - Status indicator dot: #1ADF66 90% fill, #02091A 40% outside stroke 1.5
private extension NSColor {
    static func srgb(_ hex: UInt32, alpha: CGFloat = 1.0) -> NSColor {
        NSColor(
            srgbRed: CGFloat((hex >> 16) & 0xFF) / 255.0,
            green: CGFloat((hex >> 8) & 0xFF) / 255.0,
            blue: CGFloat(hex & 0xFF) / 255.0,
            alpha: alpha
        )
    }
}

enum WidgetPalette {
    static let outerBackground = NSColor.srgb(0x02091A, alpha: 0.90)
    static let innerFill = NSColor.white.withAlphaComponent(0.04)
    static let innerStroke = NSColor.white.withAlphaComponent(0.20)
    static let separator = NSColor.white.withAlphaComponent(0.20)
    static let itemActiveBackground = NSColor.white.withAlphaComponent(0.10)
    static let labelDefault = NSColor.white.withAlphaComponent(0.70)
    static let labelActive = NSColor.white
    static let statusDotFill = NSColor.srgb(0x1ADF66, alpha: 0.90)
    static let statusDotStroke = NSColor.srgb(0x02091A, alpha: 0.40)

    static let outerCornerRadius: CGFloat = 14
    static let innerCornerRadius: CGFloat = 12
    static let itemCornerRadius: CGFloat = 8

    static let shadowOffset = CGSize(width: 0, height: -8)
    static let shadowBlurRadius: CGFloat = 16.5
    static let shadowOpacity: Float = 0.35
}
