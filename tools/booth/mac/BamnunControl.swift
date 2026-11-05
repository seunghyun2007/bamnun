// Bamnun Control: buttons for tools/booth/pi.sh, so the booth Pi can be run
// from a Mac without typing commands. Every button runs pi.sh and shows what
// it printed. Build with tools/booth/mac/build.sh.

import AppKit
import SwiftUI

@main
struct BamnunControlApp: App {
    @StateObject private var pi = Pi()

    var body: some Scene {
        WindowGroup("Bamnun Control") {
            ContentView()
                .environmentObject(pi)
                .frame(minWidth: 480, idealWidth: 520, minHeight: 700)
                .onAppear { pi.refresh() }
        }
    }
}

// MARK: - Talking to the Pi

final class Pi: ObservableObject {
    @Published var busy: String?
    @Published var output = ""
    @Published var reachable: Bool?
    @Published var route = ""
    @Published var wifi = ""
    @Published var running = false
    @Published var autostart = false
    @Published var volume: Double = 80

    let repo: URL
    var script: URL { repo.appendingPathComponent("tools/booth/pi.sh") }

    init() {
        let baked = Bundle.main.object(forInfoDictionaryKey: "BamnunRepo") as? String
        let path = ProcessInfo.processInfo.environment["BAMNUN_REPO"] ?? baked
            ?? NSString(string: "~/Downloads/bamnun").expandingTildeInPath
        repo = URL(fileURLWithPath: path)
    }

    var boothOn: Bool { wifi == "bamnun-booth" || running }

    func run(_ title: String, _ args: [String], then: ((String) -> Void)? = nil) {
        guard busy == nil else { return }
        busy = title
        say("▶ \(title)")
        let script = self.script
        DispatchQueue.global(qos: .userInitiated).async {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/bin/bash")
            p.arguments = [script.path] + args
            var env = ProcessInfo.processInfo.environment
            env["PATH"] = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            p.environment = env
            let pipe = Pipe()
            p.standardOutput = pipe
            p.standardError = pipe
            var text = ""
            do {
                try p.run()
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                p.waitUntilExit()
                text = String(decoding: data, as: UTF8.self)
            } catch {
                text = "Couldn't run \(script.path): \(error.localizedDescription)"
            }
            // Tailscale prints "# ..." notes about its own checks; keep them,
            // they hold the link to approve when it asks.
            DispatchQueue.main.async {
                self.say(text.trimmingCharacters(in: .whitespacesAndNewlines))
                self.busy = nil
                then?(text)
            }
        }
    }

    func say(_ line: String) {
        guard !line.isEmpty else { return }
        output += (output.isEmpty ? "" : "\n") + line
    }

    func refresh() {
        run("Check the Pi", ["status"]) { out in
            if out.contains("Can't reach the Pi") {
                self.reachable = false
                return
            }
            self.reachable = true
            for line in out.split(separator: "\n").map(String.init) {
                let value = line.split(separator: ":", maxSplits: 1).last
                    .map { $0.trimmingCharacters(in: .whitespaces) } ?? ""
                if line.hasPrefix("(via ") { self.route = String(line.dropFirst(5).dropLast()) }
                if line.hasPrefix("Wi-Fi:") { self.wifi = value }
                if line.hasPrefix("Autostart:") { self.autostart = value == "on" }
                if line.hasPrefix("Running:") { self.running = value == "yes" }
            }
            self.readVolume()
        }
    }

    func readVolume() {
        run("Read the volume", ["volume"]) { out in
            if let r = out.range(of: #"volume: (\d+)%"#, options: .regularExpression),
               let n = Double(out[r].filter(\.isNumber)) {
                self.volume = n
            }
        }
    }
}

// MARK: - Window

struct ContentView: View {
    @EnvironmentObject var pi: Pi
    @State private var minutes = 10
    @State private var lang = "en"
    @State private var confirm: Confirm?

    enum Confirm: Identifiable {
        case trial, on
        var id: Int { hashValue }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header
            boothBox
            deviceBox
            outputBox
            Text("While the booth is on, the Pi has no internet. To keep controlling it, join the “Bamnun-Demo” Wi-Fi on this Mac (needs this Mac’s key on the Pi once: ssh-copy-id inpi).")
                .font(.footnote).foregroundStyle(.secondary)
        }
        .padding(18)
        .disabled(pi.busy != nil)
        .alert(item: $confirm) { which in
            switch which {
            case .trial:
                return Alert(title: Text("Start the booth for \(minutes) minutes?"),
                             message: Text("The Pi switches to its own “Bamnun-Demo” Wi-Fi, so this Mac loses it until the time is up (or join Bamnun-Demo here). Then it goes back to normal Wi-Fi by itself."),
                             primaryButton: .default(Text("Start")) { pi.run("Booth on for \(minutes) min", ["try", "\(minutes)"]) { _ in pi.reachable = false } },
                             secondaryButton: .cancel())
            case .on:
                return Alert(title: Text("Turn the booth on and keep it on?"),
                             message: Text("It also starts by itself every time the Pi powers up. To stop it later: join “Bamnun-Demo” on this Mac and press Booth off."),
                             primaryButton: .default(Text("Turn on")) { pi.run("Booth on", ["on"]) { _ in pi.reachable = false } },
                             secondaryButton: .cancel())
            }
        }
    }

    var header: some View {
        HStack(spacing: 12) {
            if let img = NSImage(contentsOf: pi.repo.appendingPathComponent("assets/bamnun.png")) {
                Image(nsImage: img).resizable().frame(width: 48, height: 48)
            }
            VStack(alignment: .leading, spacing: 3) {
                Text("Bamnun Control").font(.title2.bold())
                HStack(spacing: 6) {
                    Circle().fill(dotColor).frame(width: 9, height: 9)
                    Text(statusText).font(.callout).foregroundStyle(.secondary)
                }
            }
            Spacer()
            if let busy = pi.busy {
                ProgressView().controlSize(.small)
                Text(busy + "…").font(.callout).foregroundStyle(.secondary)
            } else {
                Button { pi.refresh() } label: { Label("Refresh", systemImage: "arrow.clockwise") }
            }
        }
    }

    var dotColor: Color {
        switch pi.reachable {
        case .none: return .gray
        case .some(false): return .orange
        case .some(true): return pi.boothOn ? .green : .blue
        }
    }

    var statusText: String {
        switch pi.reachable {
        case .none: return "Checking…"
        case .some(false): return "Can't reach the Pi (booth on, or offline)"
        case .some(true):
            let how = pi.route.contains("10.42.0.1") ? "booth Wi-Fi" : "Tailscale"
            return pi.boothOn
                ? "Booth is ON · via \(how)"
                : "Booth is off · Pi on “\(pi.wifi)” · via \(how)"
        }
    }

    var boothBox: some View {
        GroupBox("Booth") {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Stepper("Try for \(minutes) min", value: $minutes, in: 5...60, step: 5).fixedSize()
                    Button("Start trial") { confirm = .trial }.buttonStyle(.borderedProminent)
                    Spacer()
                }
                HStack {
                    Button("Booth on (stays on)") { confirm = .on }
                    Button(role: .destructive) { pi.run("Booth off", ["off"]) { _ in pi.refresh() } } label: {
                        Label("Booth off", systemImage: "power")
                    }.tint(.red)
                    Spacer()
                }
                HStack {
                    Button("Restart booth") { pi.run("Restart the booth", ["restart"]) }
                    Button("Update Pi") { pi.run("Update the Pi", ["update"]) }
                    Button("Show log") { pi.run("Booth log", ["log"]) }
                    Spacer()
                }
            }.padding(6)
        }
    }

    var deviceBox: some View {
        GroupBox("Device") {
            VStack(alignment: .leading, spacing: 10) {
                Text("Wake-up stages (booth must be running)").font(.caption).foregroundStyle(.secondary)
                HStack {
                    stage(1, "Blue light", Color(red: 0.66, green: 0.61, blue: 0.94))
                    stage(2, "Mint mist", Color(red: 0.96, green: 0.71, blue: 0.78))
                    stage(3, "Chime + voice", Color(red: 0.77, green: 0.71, blue: 0.99))
                    stage(4, "Alarm", Color(red: 0.96, green: 0.56, blue: 0.69))
                }
                Divider()
                HStack {
                    Text("Ollie says").font(.caption).foregroundStyle(.secondary)
                    Picker("", selection: $lang) {
                        Text("English").tag("en")
                        Text("한국어").tag("ko")
                    }.pickerStyle(.segmented).fixedSize()
                    Spacer()
                }
                HStack {
                    Button("Hello") { pi.run("Ollie: hello", ["say", "greet", lang]) }
                    Button("Eyes closing") { pi.run("Ollie: stage 3", ["say", "stage3", lang]) }
                    Button("Wake up!") { pi.run("Ollie: stage 4", ["say", "stage4", lang]) }
                    Button("Take a break") { pi.run("Ollie: break", ["say", "break_due", lang]) }
                }
                Divider()
                HStack {
                    Image(systemName: "speaker.wave.2")
                    Slider(value: $pi.volume, in: 0...100, step: 5) { editing in
                        if !editing { pi.run("Set volume \(Int(pi.volume))%", ["volume", "\(Int(pi.volume))"]) }
                    }
                    Text("\(Int(pi.volume))%").monospacedDigit().frame(width: 44, alignment: .trailing)
                }
            }.padding(6)
        }
    }

    func stage(_ n: Int, _ name: String, _ color: Color) -> some View {
        Button { pi.run("Stage \(n)", ["stage", "\(n)"]) } label: {
            VStack(spacing: 2) {
                Text("\(n)").font(.title3.bold())
                Text(name).font(.caption2)
            }.frame(maxWidth: .infinity, minHeight: 40)
        }
        .buttonStyle(.borderedProminent).tint(color).foregroundStyle(.black)
    }

    var outputBox: some View {
        GroupBox {
            ScrollViewReader { proxy in
                ScrollView {
                    Text(pi.output.isEmpty ? " " : pi.output)
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .id("end")
                }
                .onChange(of: pi.output) { _ in proxy.scrollTo("end", anchor: .bottom) }
            }
            .frame(minHeight: 140)
        } label: {
            HStack {
                Text("What the Pi said")
                Spacer()
                Button("Clear") { pi.output = "" }.controlSize(.small)
            }
        }
    }
}
