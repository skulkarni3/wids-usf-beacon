//
//  ChatView.swift
//  WiDS_WildFire_Navigation
//

import SwiftUI

// MARK: - Date helpers

private let timeFormatter: DateFormatter = {
    let f = DateFormatter()
    f.timeStyle = .short
    f.dateStyle = .none
    return f
}()

private let dayFormatter: DateFormatter = {
    let f = DateFormatter()
    f.doesRelativeDateFormatting = true   // "Today", "Yesterday"
    f.dateStyle = .medium
    f.timeStyle = .none
    return f
}()

private func isSameDay(_ a: Date, _ b: Date) -> Bool {
    Calendar.current.isDate(a, inSameDayAs: b)
}

// MARK: - ChatView

struct ChatView: View {
    @StateObject private var chat = ChatManager()
    @EnvironmentObject var settings: SettingsManager
    @EnvironmentObject var auth: AuthManager
    @EnvironmentObject var tabRouter: MainTabRouter
    @EnvironmentObject var translations: TranslationManager
    @State private var inputText  = ""
    @State private var lastHandledVersion: Int = -1
    @State private var seeded = false
    @FocusState private var inputFocused: Bool

    private let green = Color(red: 185/255, green: 58/255,  blue: 18/255)
    private let gold  = Color(red: 205/255, green: 163/255, blue: 35/255)

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack {
                Text(translations.t("Beacon AI Agent"))
                    .font(.headline)
                    .foregroundColor(.white)
                Spacer()
                Button {
                    chat.clearHistory()
                    Task {
                        chat.settings = settings
                        chat.userId   = auth.userId
                        await chat.startSessionIfNeeded()
                    }
                } label: {
                    Image(systemName: "trash")
                        .foregroundColor(gold)
                }
            }
            .padding()
            .background(green)


            // Messages
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 4) {
                        ForEach(Array(chat.messages.enumerated()), id: \.element.id) { index, msg in
                            // Day separator before the first message of each new day
                            let prevMsg = index > 0 ? chat.messages[index - 1] : nil
                            if prevMsg == nil || !isSameDay(prevMsg!.timestamp, msg.timestamp) {
                                DaySeparator(date: msg.timestamp)
                                    .padding(.top, index == 0 ? 8 : 16)
                            }

                            MessageBubble(message: msg) { action in
                                handleChatShortcut(action)
                            }
                                .id(msg.id)
                                .padding(.bottom, 4)
                        }
                        if chat.isLoading {
                            HStack {
                                ProgressView()
                                    .tint(green)
                                    .padding(12)
                                    .background(Color(.systemGray6))
                                    .cornerRadius(16)
                                Spacer()
                            }
                            .padding(.horizontal)
                            .id("loading")
                        }
                    }
                    .padding(.vertical, 4)
                }
                .onChange(of: chat.messages.count) {
                    if let last = chat.messages.last {
                        withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                    }
                }
                .onChange(of: chat.scrollTick) {
                    if let last = chat.messages.last {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
                .onChange(of: chat.isLoading) { _, loading in
                    if loading { withAnimation { proxy.scrollTo("loading", anchor: .bottom) } }
                }
            }

            if let err = chat.errorMsg {
                Text(err)
                    .font(.caption)
                    .foregroundColor(.red)
                    .padding(.horizontal)
            }

            Divider()

            // Input bar
            HStack(spacing: 8) {
                TextField("Talk to Beacon AI Agent…", text: $inputText, axis: .vertical)
                    .lineLimit(1...4)
                    .padding(10)
                    .background(Color(.systemGray6))
                    .cornerRadius(20)
                    .focused($inputFocused)
                    .onSubmit { sendMessage() }
                    .submitLabel(.send)

                Button { sendMessage() } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 32))
                        .foregroundColor(inputText.trimmingCharacters(in: .whitespaces).isEmpty ? .gray : green)
                }
                .disabled(inputText.trimmingCharacters(in: .whitespaces).isEmpty || chat.isLoading)
            }
            .padding(.horizontal)
            .padding(.vertical, 8)
            .background(Color(.systemBackground))
        }
        .task(id: settings.sessionVersion) {
            chat.settings = settings
            chat.userId   = auth.userId
            let version = settings.sessionVersion
            if !seeded {
                // First appearance — record current version without clearing.
                seeded = true
                lastHandledVersion = version
            } else if version != lastHandledVersion {
                // Genuinely new settings change — clear and restart.
                try? await Task.sleep(for: .milliseconds(800))
                guard !Task.isCancelled else { return }
                lastHandledVersion = version
                chat.clearHistory()
            }
            await chat.startSessionIfNeeded()
        }
    }

    private func sendMessage() {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !chat.isLoading else { return }
        inputText = ""
        inputFocused = false
        Task { await chat.send(text) }
    }

    private func handleChatShortcut(_ action: ChatAction) {
        switch action.id {
        case "open_onboarding":
            auth.openOnboardingEditor()
        case "open_checklist":
            tabRouter.select(.checklist)
        case "open_map":
            tabRouter.select(.map)
        case "open_settings", "open_language":
            tabRouter.select(.settings)
        // Drop-by reply chips — auto-send a message so Claude can react.
        case "add_dropby":
            Task { await chat.send("Yes, add a drop-by stop to my route") }
        case "skip_dropby":
            Task { await chat.send("No, skip the drop-by stop") }
        default:
            break
        }
    }
}

// MARK: - Day Separator

struct DaySeparator: View {
    let date: Date

    var body: some View {
        HStack {
            line
            Text(dayFormatter.string(from: date))
                .font(.caption)
                .foregroundColor(.secondary)
                .padding(.horizontal, 8)
            line
        }
        .padding(.horizontal)
    }

    private var line: some View {
        Rectangle()
            .fill(Color(.systemGray4))
            .frame(height: 0.5)
    }
}

// MARK: - Message Bubble

struct MessageBubble: View {
    let message: ChatMessage
    var onShortcut: ((ChatAction) -> Void)? = nil

    private let green = Color(red: 185/255, green: 58/255, blue: 18/255)

    var isUser: Bool { message.role == "user" }

    var body: some View {
        HStack(alignment: .bottom) {
            if isUser { Spacer(minLength: 48) }

            VStack(alignment: isUser ? .trailing : .leading, spacing: 3) {
                Text(attributedContent)
                    .padding(12)
                    .background(isUser ? green : Color(.systemGray6))
                    .foregroundColor(isUser ? .white : .primary)
                    .cornerRadius(16)

                if !isUser, let actions = message.actions, !actions.isEmpty, let onShortcut {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(actions) { action in
                            Button {
                                onShortcut(action)
                            } label: {
                                Text(action.label)
                                    .font(.subheadline.weight(.semibold))
                                    .multilineTextAlignment(.leading)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .buttonStyle(.borderedProminent)
                            .tint(green)
                        }
                    }
                    .padding(.top, 2)
                }

                Text(timeFormatter.string(from: message.timestamp))
                    .font(.caption2)
                    .foregroundColor(.secondary)
                    .padding(.horizontal, 4)

            }

            if !isUser { Spacer(minLength: 48) }
        }
        .padding(.horizontal)
    }

    private var attributedContent: AttributedString {
        var processed = message.content

        // Strip heading markers (## / #) — inline mode renders them as literal text.
        processed = processed.replacingOccurrences(of: "(?m)^#{1,6} ", with: "",
                                                   options: .regularExpression)

        // Convert bullet lines ("* item") to unicode bullets.
        // Require a space after * so we don't clobber *italic* markers at line start.
        processed = processed.replacingOccurrences(of: "(?m)^\\* ", with: "• ",
                                                   options: .regularExpression)

        // Strip blockquote markers ("> ") — inline mode renders them as literal ">".
        processed = processed.replacingOccurrences(of: "(?m)^> ?", with: "",
                                                   options: .regularExpression)

        // Flatten markdown tables into readable plain lines.
        // 1. Remove separator rows like |---|---| or |:---|---:|
        processed = processed.replacingOccurrences(of: "(?m)^\\|[\\s\\-|:]+\\|\\s*$\n?", with: "",
                                                   options: .regularExpression)
        // 2. Strip leading "| " from table rows
        processed = processed.replacingOccurrences(of: "(?m)^\\| ?", with: "",
                                                   options: .regularExpression)
        // 3. Strip trailing " |" from table rows
        processed = processed.replacingOccurrences(of: "(?m) ?\\|\\s*$", with: "",
                                                   options: .regularExpression)
        // 4. Replace inner column separators " | " with a readable dash
        processed = processed.replacingOccurrences(of: " \\| ", with: "  –  ")

        // Replace standalone --- dividers only (not table cell content).
        processed = processed.replacingOccurrences(of: "(?m)^---$", with: "──────────────",
                                                   options: .regularExpression)

        // inlineOnlyPreservingWhitespace keeps real \n characters as line breaks.
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        return (try? AttributedString(markdown: processed, options: options))
            ?? AttributedString(processed)
    }
}
