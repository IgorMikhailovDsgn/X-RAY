import XCTest
@testable import BrainScan

final class ActionButtonViewTests: XCTestCase {
    func test_default_state_is_default_for_enabled_button() {
        let button = ActionButtonView(icon: .detect, label: "Detect")
        XCTAssertEqual(button.state, .default)
    }

    func test_disabled_button_starts_in_disabled_state() {
        let button = ActionButtonView(icon: .detect, label: "Detect", enabled: false)
        XCTAssertEqual(button.state, .disabled)
    }

    func test_setEnabled_false_moves_to_disabled() {
        let button = ActionButtonView(icon: .detect, label: "Detect")
        button.setEnabled(false)
        XCTAssertEqual(button.state, .disabled)
    }

    func test_setEnabled_true_returns_to_default() {
        let button = ActionButtonView(icon: .detect, label: "Detect", enabled: false)
        button.setEnabled(true)
        XCTAssertEqual(button.state, .default)
    }
}
