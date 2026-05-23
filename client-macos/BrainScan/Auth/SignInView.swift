import SwiftUI

/// VM экрана входа: вводит email/password, дёргает `APIClient.login`, сохраняет
/// токены в `TokenStore`. При успехе зовёт `onSignedIn`.
@MainActor
final class SignInViewModel: ObservableObject {
    @Published var email = ""
    @Published var password = ""
    @Published var isLoading = false
    @Published var errorMessage: String?

    var onSignedIn: (() -> Void)?

    private let client: APIClient
    private let tokenStore: TokenStore

    init(client: APIClient = .shared, tokenStore: TokenStore = TokenStore()) {
        self.client = client
        self.tokenStore = tokenStore
    }

    var canSubmit: Bool { !email.isEmpty && !password.isEmpty && !isLoading }

    func signIn() {
        guard canSubmit else { return }
        isLoading = true
        errorMessage = nil
        Task { [email, password] in
            do {
                let pair = try await client.login(email: email, password: password)
                try? tokenStore.save(pair)
                isLoading = false
                onSignedIn?()
            } catch {
                isLoading = false
                errorMessage = (error as? LocalizedError)?.errorDescription
                    ?? "Sign in failed. Please try again."
            }
        }
    }
}

/// Минимальный нативный экран входа: email + password + Sign In. MVP без
/// регистрации/восстановления — учётка заводится в БД на стороне бэкенда.
struct SignInView: View {
    @ObservedObject var viewModel: SignInViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Sign in to BrainScan")
                .font(.title2.weight(.semibold))

            VStack(alignment: .leading, spacing: 6) {
                Text("Email").font(.callout).foregroundStyle(.secondary)
                TextField("you@example.com", text: $viewModel.email)
                    .textFieldStyle(.roundedBorder)
                    .disableAutocorrection(true)
                    .onSubmit(viewModel.signIn)
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("Password").font(.callout).foregroundStyle(.secondary)
                SecureField("", text: $viewModel.password)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit(viewModel.signIn)
            }

            if let message = viewModel.errorMessage {
                Text(message)
                    .foregroundStyle(.red)
                    .font(.callout)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 4)

            HStack {
                Spacer()
                Button(action: viewModel.signIn) {
                    if viewModel.isLoading {
                        ProgressView().controlSize(.small)
                            .frame(minWidth: 60)
                    } else {
                        Text("Sign In").frame(minWidth: 60)
                    }
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .disabled(!viewModel.canSubmit)
            }
        }
        .padding(24)
        .frame(width: 380, height: 280)
    }
}
