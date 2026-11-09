import SwiftUI

struct MealsView: View {
    @EnvironmentObject var store: HouseholdStore
    @State private var adding = false
    var body: some View {
        List {
            Section("Meal collection") {
                ForEach(store.collection.meals.filter { $0.active == 1 }) { meal in
                    NavigationLink { MealEditorView(meal: meal) } label: {
                        VStack(alignment: .leading) { Text(meal.mealDescription); Text("\(meal.mealType) · serves \(meal.servings)").font(.caption).foregroundStyle(.secondary) }
                    }.disabled(store.busy)
                }
            }
            if store.collection.meals.contains(where: { $0.active == 0 }) {
                Section("Archived meals") { ForEach(store.collection.meals.filter { $0.active == 0 }) { meal in NavigationLink(meal.mealDescription) { MealEditorView(meal: meal) } } }
            }
        }
        .navigationTitle("Meals")
        .toolbar { Button { adding = true } label: { Label("Add meal", systemImage: "plus") }.disabled(store.busy || store.offline) }
        .refreshable { await store.refresh() }
        .sheet(isPresented: $adding) { NavigationStack { MealEditorView(meal: nil) } }
    }
}

struct EditableIngredient: Identifiable {
    let id = UUID()
    var name = ""
    var amount = ""
    var unit = "each"
}

struct MealEditorView: View {
    @EnvironmentObject var store: HouseholdStore
    @Environment(\.dismiss) var dismiss
    @State private var record: Meal?
    @State private var name: String
    @State private var type: String
    @State private var effort: Int
    @State private var theme: String
    @State private var servings: String
    @State private var entries: [EditableIngredient] = []
    @State private var loaded = false
    @State private var archiving = false

    init(meal: Meal?) {
        _record = State(initialValue: meal)
        _name = State(initialValue: meal?.mealDescription ?? "")
        _type = State(initialValue: meal?.mealType ?? "dinner")
        _effort = State(initialValue: meal?.effortLevel ?? 0)
        _theme = State(initialValue: meal?.theme ?? "")
        _servings = State(initialValue: meal?.servings ?? "1")
    }

    var body: some View {
        Form {
            Section("Meal details") {
                TextField("Meal name", text: $name)
                Picker("Mealtime", selection: $type) { Text("Dinner").tag("dinner"); Text("Lunch").tag("lunch"); Text("Breakfast").tag("breakfast") }
                EffortPicker(value: $effort)
                if ![0, 1, 2, 3].contains(effort) { Text("This meal has a legacy effort value. Choose quick, moderate, or involved to update it.").font(.caption) }
                TextField("Theme (optional)", text: $theme)
                TextField("Ingredient amounts serve", text: $servings).keyboardType(.decimalPad)
                Button(record == nil ? "Add meal" : "Save meal details") { Task { await saveDetails() } }.disabled(store.busy || store.offline || name.isEmpty)
            }
            if let record {
                Section("Ingredients for \(servings) servings") {
                    if record.active == 0 {
                        Text("This meal is archived. Restore it before changing ingredients.")
                        Button("Restore meal") { Task { await store.perform {
                            guard let api = store.api else { return }
                            self.record = try await api.restoreMeal(record)
                            try await store.reloadAfterCollectionChange()
                        } } }.disabled(store.busy || store.offline)
                    } else {
                        if !loaded { Button("Load ingredients") { Task { await loadIngredients() } } }
                        ForEach($entries) { $entry in
                            VStack(alignment: .leading) {
                                TextField("Ingredient", text: $entry.name)
                                HStack { TextField("Amount", text: $entry.amount).keyboardType(.decimalPad); TextField("Unit (g, ml, each…)", text: $entry.unit) }
                            }
                        }.onDelete { entries.remove(atOffsets: $0) }
                        Button("Add ingredient row") { entries.append(EditableIngredient()) }
                        Button("Save ingredients") { Task { await saveIngredients() } }.disabled(store.busy || store.offline || !loaded)
                        Text("Amounts are for the meal yield above. Compatible units combine on the shopping list. Cups, teaspoons and tablespoons are US measures.").font(.caption)
                    }
                }.disabled(store.offline)
                if record.active == 1 { Section { Button("Archive meal", role: .destructive) { archiving = true }.disabled(store.busy || store.offline) } }
            } else {
                Section { Text("Add the named meal first, then record its ingredients. Recipe instructions are optional.") }
            }
            ErrorSection()
        }
        .navigationTitle(record?.mealDescription ?? "New meal")
        .toolbar { Button("Done") { dismiss() } }
        .task { if record != nil && !store.offline { await loadIngredients() } }
        .confirmationDialog("Archive this meal? Saved plans keep their history.", isPresented: $archiving, titleVisibility: .visible) {
            Button("Archive meal", role: .destructive) { Task { await store.perform {
                guard let api = store.api, let record else { return }
                try await api.archiveMeal(record); try await store.reloadAfterCollectionChange(); dismiss()
            } } }
        }
    }
    private func saveDetails() async {
        await store.perform {
            guard let api = store.api else { return }
            if let record { self.record = try await api.updateMeal(record, name: name, type: type, effort: effort == 0 ? nil : effort, theme: theme, servings: servings) }
            else { self.record = try await api.addMeal(name: name, type: type, effort: effort == 0 ? nil : effort, theme: theme, servings: servings); loaded = true }
            try await store.reloadAfterCollectionChange()
            store.notice = "Meal details saved."
        }
    }
    private func loadIngredients() async {
        await store.perform {
            guard let api = store.api, let record else { return }
            entries = try await api.ingredients(record.mealId).map { EditableIngredient(name: $0.name, amount: $0.amount, unit: $0.unit) }
            loaded = true
        }
    }
    private func saveIngredients() async {
        await store.perform {
            guard let api = store.api, let record else { return }
            let rows = entries.filter { !$0.name.isEmpty || !$0.amount.isEmpty }.map { ["name": $0.name, "amount": $0.amount, "unit": $0.unit] }
            _ = try await api.saveIngredients(meal: record.mealId, entries: rows)
            try await store.reloadAfterCollectionChange()
            store.notice = "Ingredients saved."
        }
    }
}
