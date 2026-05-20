import AppKit

/// «XR» лейбл для menubar — только текст, без подложки. Inter Bold Italic
/// (fallback на system bold italic). Template-образ — менюбар сам красит
/// под light/dark, как требуют гайдлайны macOS.
enum MenubarIconRenderer {
    static func makeXRLabel() -> NSImage {
        let font = preferredFont(size: 13)
        let attrs: [NSAttributedString.Key: Any] = [
            .font: font,
            .foregroundColor: NSColor.black,   // для template важен только alpha-силуэт
        ]
        let text = NSAttributedString(string: "XR", attributes: attrs)
        let textSize = text.size()
        let size = NSSize(width: ceil(textSize.width), height: ceil(textSize.height))

        let image = NSImage(size: size, flipped: false) { rect in
            text.draw(in: rect)
            return true
        }
        image.isTemplate = true
        return image
    }

    private static func preferredFont(size: CGFloat) -> NSFont {
        if let inter = NSFont(name: "Inter-BoldItalic", size: size) {
            return inter
        }
        let system = NSFont.systemFont(ofSize: size, weight: .bold)
        return NSFontManager.shared.convert(system, toHaveTrait: .italicFontMask)
    }
}
