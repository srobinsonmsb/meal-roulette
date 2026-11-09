import SwiftUI

func weekDates(_ start: String) -> [String] {
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.timeZone = TimeZone(secondsFromGMT: 0)
    formatter.dateFormat = "yyyy-MM-dd"
    guard let date = formatter.date(from: start) else { return [] }
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = TimeZone(secondsFromGMT: 0)!
    return (0..<7).compactMap { calendar.date(byAdding: .day, value: $0, to: date).map { formatter.string(from: $0) } }
}

struct SlotSelection: Identifiable {
    let day: String
    let mealType: String
    var id: String { day + mealType }
}

struct PlansView: View {
    @EnvironmentObject var store: HouseholdStore
    @State private var newPlan = false
    @State private var regenerate = false
    @State private var selection: SlotSelection?
    var body: some View {
        List {
            if let plan = store.selectedPlan {
                Section {
                    Picker("Saved week", selection: Binding(get: { plan.planId }, set: { id in Task { await store.select(id) } })) {
                        ForEach(store.plans) { summary in Text(summary.weekStart + " · " + summary.state).tag(summary.planId) }
                    }
                    Text(plan.state == "confirmed" ? "Confirmed household plan" : "Draft household plan").font(.headline)
                    if plan.state == "draft" {
                        Button("Confirm this plan") { Task { await store.confirm() } }.disabled(store.busy || store.offline)
                        Button("Regenerate unchosen meals") { regenerate = true }.disabled(store.busy || store.offline)
                    } else {
                        Button("Preview Calendar publication") { Task { await publish(dryRun: true) } }.disabled(store.busy || store.offline)
                        if store.calendarEnabled { Button("Publish to Google Calendar") { Task { await publish(dryRun: false) } }.disabled(store.busy || store.offline) }
                    }
                    if let job = plan.calendarJob { Text(job.lastError ?? "Calendar update queued.").font(.caption).foregroundStyle(.secondary) }
                    if let notice = store.notice { Text(notice).font(.caption) }
                }
                ForEach(weekDates(plan.weekStart), id: \.self) { day in
                    Section(day) {
                        ForEach(plan.mealTypes, id: \.self) { type in
                            ForEach(plan.assignments.filter { $0.date == day && $0.mealType == type }) { assignment in
                                AssignmentRow(assignment: assignment)
                            }
                            Button("\(type.capitalized) settings · who's eating?") { selection = SlotSelection(day: day, mealType: type) }
                                .font(.caption).disabled(store.busy || store.offline)
                        }
                    }
                }
            } else {
                Section {
                    Text("Make your first weekly plan").font(.headline)
                    Text("Add household members, meals and preference lists in Settings and Meals, then create a week.")
                }
            }
        }
        .navigationTitle("Weekly plans")
        .toolbar { Button { newPlan = true } label: { Label("New plan", systemImage: "plus") }.disabled(store.busy || store.offline) }
        .refreshable { await store.refresh() }
        .sheet(isPresented: $newPlan) { NavigationStack { NewPlanView() } }
        .sheet(item: $selection) { choice in NavigationStack { SlotEditor(choice: choice) } }
        .confirmationDialog("Regenerate meals you haven't deliberately chosen? Your manual choices remain.", isPresented: $regenerate, titleVisibility: .visible) {
            Button("Regenerate unchosen meals") { Task { await store.regenerate() } }
        }
    }
    private func publish(dryRun: Bool) async {
        await store.perform {
            guard let api = store.api, let plan = store.selectedPlan else { return }
            let publication = try await api.publish(plan, dryRun: dryRun)
            store.notice = publication.dryRun ? "Preview: \(publication.events) Calendar events." : "Updated \(publication.events) Calendar events."
            try await store.reloadAfterCollectionChange()
        }
    }
}

struct AssignmentRow: View {
    @EnvironmentObject var store: HouseholdStore
    let assignment: Assignment
    @State private var choosing = false
    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text(assignment.eaterName + " · " + assignment.mealType).font(.caption).foregroundStyle(.secondary)
                Text(assignment.label)
                if let reason = assignment.reason { Text(reason).font(.caption).foregroundStyle(.secondary) }
            }
            Spacer()
            Menu {
                Button("Choose a meal") { choosing = true }
                Button("Reroll") { Task { await store.change(assignment, action: "reroll") } }
                Button("Eating out") { Task { await store.change(assignment, action: "eating_out") } }
                Button("Leftovers") { Task { await store.change(assignment, action: "leftovers") } }
            } label: { Image(systemName: "ellipsis.circle").padding(8) }
            .accessibilityLabel("Change \(assignment.eaterName)'s \(assignment.mealType)")
            .disabled(store.busy || store.offline)
        }
        .sheet(isPresented: $choosing) { NavigationStack { ChooseMealView(assignment: assignment) } }
    }
}

struct ChooseMealView: View {
    @EnvironmentObject var store: HouseholdStore
    @Environment(\.dismiss) var dismiss
    let assignment: Assignment
    var body: some View {
        List(store.collection.meals.filter { $0.active == 1 && $0.mealType == assignment.mealType }) { meal in
            Button(meal.mealDescription) {
                Task { await store.change(assignment, action: "meal", mealId: meal.mealId); if store.errorMessage == nil { dismiss() } }
            }.disabled(store.busy || store.offline)
        }
        .navigationTitle("Choose a meal")
        .toolbar { Button("Cancel") { dismiss() } }
    }
}

struct NewPlanView: View {
    @EnvironmentObject var store: HouseholdStore
    @Environment(\.dismiss) var dismiss
    @State private var start = Calendar(identifier: .iso8601).dateInterval(of: .weekOfYear, for: Date())!.start
    @State private var breakfast = false
    @State private var lunch = false
    @State private var dinner = true
    var body: some View {
        Form {
            DatePicker("Week starting Monday", selection: $start, displayedComponents: .date)
            Toggle("Breakfast", isOn: $breakfast)
            Toggle("Lunch", isOn: $lunch)
            Toggle("Dinner", isOn: $dinner)
            ErrorSection()
            Button("Create draft") {
                let formatter = DateFormatter(); formatter.locale = Locale(identifier: "en_US_POSIX"); formatter.dateFormat = "yyyy-MM-dd"
                let types = [("breakfast", breakfast), ("lunch", lunch), ("dinner", dinner)].filter { $0.1 }.map { $0.0 }
                Task { await store.create(week: formatter.string(from: start), mealTypes: types); if store.errorMessage == nil { dismiss() } }
            }.disabled(store.busy || store.offline || (!breakfast && !lunch && !dinner))
        }
        .navigationTitle("New weekly plan")
        .toolbar { Button("Cancel") { dismiss() } }
    }
}

struct SlotEditor: View {
    @EnvironmentObject var store: HouseholdStore
    @Environment(\.dismiss) var dismiss
    let choice: SlotSelection
    @State private var diners: Set<Int> = []
    @State private var shared = true
    @State private var kind = "meal"
    @State private var effort = 0
    @State private var theme = ""
    var body: some View {
        Form {
            Section("Who is eating?") {
                ForEach(store.collection.eaters.filter { $0.active == 1 }) { eater in
                    Toggle(eater.name, isOn: Binding(get: { diners.contains(eater.eaterId) }, set: { on in if on { diners.insert(eater.eaterId) } else { diners.remove(eater.eaterId) } }))
                }
            }
            Section {
                Toggle("Eat together", isOn: $shared)
                Picker("Dinner choice", selection: $kind) { Text("Choose a meal").tag("meal"); Text("Eating out").tag("eating_out"); Text("Leftovers").tag("leftovers") }
                EffortPicker(value: $effort, maximum: true)
                TextField("Theme (optional)", text: $theme)
                Text("This exception replaces the choices for this dinner only. Reusable routines stay unchanged.").font(.caption)
            }
            ErrorSection()
            Button("Apply this week's exception") {
                Task { await store.perform {
                    guard let api = store.api, let plan = store.selectedPlan else { return }
                    store.selectedPlan = try await api.override(plan, day: choice.day, mealType: choice.mealType, diners: Array(diners).sorted(), shared: shared, kind: kind, effort: effort == 0 ? nil : effort, theme: theme)
                    try await store.reloadAfterCollectionChange(); dismiss()
                } }
            }.disabled(store.busy || store.offline)
        }
        .navigationTitle(choice.day + " · " + choice.mealType)
        .toolbar { Button("Cancel") { dismiss() } }
        .onAppear {
            let slots = store.selectedPlan?.assignments.filter { $0.date == choice.day && $0.mealType == choice.mealType } ?? []
            diners = Set(slots.map(\.eaterId)); shared = slots.first?.groupMeal ?? true
            kind = slots.first?.kind ?? "meal"; effort = slots.first?.maxEffort ?? 0; theme = slots.first?.theme ?? ""
        }
    }
}

struct EffortPicker: View {
    @Binding var value: Int
    var maximum = false
    var body: some View {
        Picker(maximum ? "Maximum effort" : "Effort", selection: $value) {
            Text(maximum ? "Any effort" : "Not recorded").tag(0)
            Text("Quick").tag(1); Text("Moderate").tag(2); Text("Involved").tag(3)
        }
    }
}

struct ErrorSection: View {
    @EnvironmentObject var store: HouseholdStore
    var body: some View { if let error = store.errorMessage { Section { Text(error).foregroundStyle(.red) } } }
}
