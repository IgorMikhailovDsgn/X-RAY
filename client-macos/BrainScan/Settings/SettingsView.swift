import SwiftUI

/// Нативное содержимое окна настроек. GroupBox + Toggle(.switch) дают
/// системный grouped-вид, всё адаптируется к light/dark автоматически.
struct SettingsView: View {
    let statusText: String
    let statusColor: Color
    let statusMeta: String

    @State private var allowScreenshot = true
    @State private var notifications = true
    @State private var keyboardShortcuts = true

    private let shortcuts: [(name: String, keys: String)] = [
        ("Show widget", "⇧⌘⏎"),
        ("Hide widget", "⇧⌘X"),
        ("Settings", "⌘S"),
        ("Detect", "⌘D"),
        ("Discard detection", "⌘X"),
        ("Annotate", "⇧⌘A"),
        ("Confirm detection", "⇧⌘C"),
        ("Edit detection", "⇧⌘E"),
        ("Send annotation", "⌥⌘⏎"),
    ]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                statusRow

                GroupBox("Permissions") {
                    VStack(spacing: 12) {
                        toggleRow(
                            "Allow screenshot",
                            "When enabled, the app can take screenshots and send them to models.",
                            $allowScreenshot
                        )
                        Divider()
                        toggleRow(
                            "Notifications",
                            "When enabled, the app can notify you in the system tray.",
                            $notifications
                        )
                        Divider()
                        toggleRow(
                            "Keyboard shortcuts",
                            "When enabled, you can use keyboard shortcuts.",
                            $keyboardShortcuts
                        )
                    }
                    .padding(8)
                }

                GroupBox("Keyboard Shortcuts") {
                    VStack(spacing: 8) {
                        ForEach(Array(shortcuts.enumerated()), id: \.element.name) { index, item in
                            HStack {
                                Text(item.name)
                                Spacer()
                                Text(item.keys)
                                    .foregroundStyle(.secondary)
                                    .font(.system(.body, design: .monospaced))
                            }
                            if index < shortcuts.count - 1 {
                                Divider()
                            }
                        }
                    }
                    .padding(8)
                }

                GroupBox("Account") {
                    HStack {
                        Text("Igor Mikhailov").fontWeight(.medium)
                        Spacer()
                        Button("Change…") {}
                    }
                    .padding(8)
                }
            }
            .padding(20)
        }
        .frame(width: 460, height: 620)
    }

    private var statusRow: some View {
        HStack(spacing: 6) {
            Circle().fill(statusColor).frame(width: 8, height: 8)
            Text(statusText).fontWeight(.medium)
            if !statusMeta.isEmpty {
                Text(statusMeta)
                    .foregroundStyle(.secondary)
                    .font(.subheadline)
            }
            Spacer()
        }
    }

    private func toggleRow(
        _ title: String,
        _ helper: String,
        _ binding: Binding<Bool>
    ) -> some View {
        Toggle(isOn: binding) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                Text(helper)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .toggleStyle(.switch)
        .frame(maxWidth: .infinity)
    }
}
