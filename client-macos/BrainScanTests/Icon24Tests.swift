import XCTest
@testable import BrainScan

final class Icon24Tests: XCTestCase {
    func test_all_icons_resolve_to_a_template_image() {
        for icon in Icon24.allCases {
            let image = icon.makeImage()
            XCTAssertTrue(
                image.isTemplate,
                "Icon24.\(icon) image must be template so AppKit перекрашивает её."
            )
            XCTAssertGreaterThan(image.size.width, 0, "Icon24.\(icon) has zero width")
            XCTAssertGreaterThan(image.size.height, 0, "Icon24.\(icon) has zero height")
        }
    }

    func test_symbol_names_match_expected_sf_symbols() {
        XCTAssertEqual(Icon24.close.symbolName, "xmark.circle.fill")
        XCTAssertEqual(Icon24.annotate.symbolName, "text.bubble")
        XCTAssertEqual(Icon24.detect.symbolName, "dot.viewfinder")
        XCTAssertEqual(Icon24.settings.symbolName, "gearshape.fill")
        XCTAssertEqual(Icon24.check.symbolName, "checkmark")
        XCTAssertEqual(Icon24.send.symbolName, "paperplane.fill")
    }

    func test_custom_asset_icons_have_asset_names() {
        XCTAssertEqual(Icon24.close.assetName, "icon-close")
        XCTAssertEqual(Icon24.annotate.assetName, "icon-annotate")
        XCTAssertEqual(Icon24.detect.assetName, "icon-detect")
        XCTAssertEqual(Icon24.settings.assetName, "icon-settings")
        XCTAssertNil(Icon24.check.assetName, "check пока без кастомного ассета")
        XCTAssertNil(Icon24.send.assetName, "send пока без кастомного ассета")
    }
}
