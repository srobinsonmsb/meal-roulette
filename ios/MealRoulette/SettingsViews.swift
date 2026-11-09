import SwiftUI

struct HouseholdSettingsView: View {
    @EnvironmentObject var store: HouseholdStore
    var body: some View {
        List {
            Section("Your household") {
                NavigationLink("Members and preferences") { PreferencesView() }
                NavigationLink("Weekly routines") { RoutinesView() }
                NavigationLink("Server connection and local cache") { ServerSettingsView() }
            }
            Section("Data ownership") {
                Text("This client talks directly to your household server. It has no vendor login, advertising SDK, or central collection of your meal data.")
                if let api = store.api { Link("Export household data", destination: api.baseURL.appendingPathComponent("api/export")) }
                if let last = store.lastSynced { Text("Phone copy last updated \(last.formatted(date: .abbreviated, time: .shortened))").font(.caption) }
            }
        }.navigationTitle("Household")
    }
}

struct ServerSettingsView: View {
    @EnvironmentObject var store: HouseholdStore
    @State private var address = ""
    var body: some View {
        Form {
            Section("Household server") {
                TextField("https://your-server.ts.net", text: $address).keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                    .accessibilityIdentifier("server-address")
                Text("Use your household's local server or Tailscale Serve address. Away from home, connect Tailscale on this phone first.").font(.caption)
                Button("Connect") { Task { await store.connect(address: address) } }.disabled(store.busy || address.isEmpty)
            }
            if !store.serverAddress.isEmpty {
                Section("This phone") {
                    if let last = store.lastSynced { Text("Saved copy: \(last.formatted(date: .abbreviated, time: .shortened))") }
                    Text("Cached plans and groceries can be read offline. Reconnect before making changes.").font(.caption)
                    Button("Clear this phone's cache") { store.clearCache() }
                    Button("Disconnect this phone", role: .destructive) { store.disconnect(); address = "" }
                    Text("These actions do not delete data on the household server.").font(.caption)
                }
            }
            ErrorSection()
        }.navigationTitle("Server connection").onAppear { address = store.serverAddress }
    }
}

struct PreferencesView: View {
    @EnvironmentObject var store: HouseholdStore
    @State private var name = ""
    var body: some View {
        Form {
            ForEach(store.collection.eaters.filter { $0.active == 1 }) { eater in
                Section(eater.name) {
                    ForEach(store.collection.meals.filter { $0.active == 1 }) { meal in
                        Toggle(meal.mealDescription, isOn: Binding(get: {
                            store.collection.preferences.contains { $0.eaterId == eater.eaterId && $0.mealId == meal.mealId }
                        }, set: { approved in Task { await store.perform {
                            guard let api = store.api else { return }
                            try await api.setPreference(eater: eater.eaterId, meal: meal.mealId, approved: approved)
                            try await store.reloadAfterCollectionChange()
                        } } })).disabled(store.busy || store.offline)
                    }
                }
            }
            Section("Add household member") {
                TextField("Name", text: $name)
                Button("Add member") { Task { await store.perform {
                    guard let api = store.api else { return }
                    try await api.addEater(name: name); name = ""; try await store.reloadAfterCollectionChange()
                } } }.disabled(name.isEmpty || store.busy || store.offline)
            }
            Section { Text("Only meals on a person's preference list are eligible for automatic selection. Shared dinners require approval from everyone eating.").font(.caption) }
            ErrorSection()
        }.navigationTitle("Members & preferences")
    }
}

let weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

struct RoutinesView: View {
    @EnvironmentObject var store: HouseholdStore
    @State private var adding = false
    @State private var editing: Routine?
    var body: some View {
        List {
            Section { Text("Reusable defaults for new plans. Individual weeks and deliberate choices can make exceptions.").font(.caption) }
            ForEach(store.collection.routines) { routine in
                Button { editing = routine } label: {
                    VStack(alignment: .leading) { Text(weekdays[routine.weekday] + " · " + routine.mealType); Text(routine.kind.replacingOccurrences(of: "_", with: " ") + (routine.theme.isEmpty ? "" : " · " + routine.theme)).font(.caption) }
                }.disabled(store.offline || store.busy)
                .swipeActions { Button("Remove", role: .destructive) { Task { await store.perform {
                    guard let api = store.api else { return }
                    try await api.deleteRoutine(routine); try await store.reloadAfterCollectionChange()
                } } }.disabled(store.offline || store.busy) }
            }
        }
        .navigationTitle("Weekly routines")
        .toolbar { Button { adding = true } label: { Label("Add routine", systemImage: "plus") }.disabled(store.offline || store.busy) }
        .sheet(isPresented: $adding) { NavigationStack { RoutineEditor(routine: nil) } }
        .sheet(item: $editing) { routine in NavigationStack { RoutineEditor(routine: routine) } }
    }
}

struct RoutineEditor: View {
    @EnvironmentObject var store: HouseholdStore
    @Environment(\.dismiss) var dismiss
    let routine: Routine?
    @State private var day = 0
    @State private var mealType = "dinner"
    @State private var shared = true
    @State private var kind = "meal"
    @State private var effort = 0
    @State private var theme = ""
    var body: some View {
        Form {
            Picker("Day", selection: $day) { ForEach(0..<7) { Text(weekdays[$0]).tag($0) } }.disabled(routine != nil)
            Picker("Mealtime", selection: $mealType) { Text("Dinner").tag("dinner"); Text("Lunch").tag("lunch"); Text("Breakfast").tag("breakfast") }.disabled(routine != nil)
            Toggle("Eat together", isOn: $shared)
            Picker("Dinner choice", selection: $kind) { Text("Choose a meal").tag("meal"); Text("Eating out").tag("eating_out"); Text("Leftovers").tag("leftovers") }
            EffortPicker(value: $effort, maximum: true)
            TextField("Theme (optional)", text: $theme)
            ErrorSection()
            Button("Save routine") { Task { await store.perform {
                guard let api = store.api else { return }
                try await api.saveRoutine(day: day, mealType: mealType, shared: shared, kind: kind, effort: effort == 0 ? nil : effort, theme: theme)
                try await store.reloadAfterCollectionChange(); dismiss()
            } } }.disabled(store.busy || store.offline)
        }.navigationTitle("Weekly routine").toolbar { Button("Cancel") { dismiss() } }
            .onAppear { if let routine { day = routine.weekday; mealType = routine.mealType; shared = routine.groupMeal == 1; kind = routine.kind; effort = routine.maxEffort ?? 0; theme = routine.theme } }
    }
}
