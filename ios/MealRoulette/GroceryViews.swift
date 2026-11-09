import SwiftUI

struct GroceriesView: View {
    @EnvironmentObject var store: HouseholdStore
    @State private var adding = false
    var body: some View {
        List {
            if let list = store.groceries {
                Section { Text("Week of " + list.weekStart) }
                if !list.warnings.isEmpty { Section("Incomplete ingredient coverage") { ForEach(list.warnings, id: \.self) { Text($0).font(.caption) } } }
                Section("To buy") { ForEach(list.items.filter { !$0.isDone }) { row in GroceryRow(item: row) } }
                Section("Purchased or already at home") { ForEach(list.items.filter(\.isDone)) { row in GroceryRow(item: row) } }
            } else {
                Text("Choose or create a meal plan to build its shared grocery list.")
            }
        }
        .navigationTitle("Groceries")
        .refreshable { await store.refresh() }
        .toolbar { Button { adding = true } label: { Label("Add item", systemImage: "plus") }.disabled(store.groceries == nil || store.busy || store.offline) }
        .sheet(isPresented: $adding) { NavigationStack { AddGroceryView() } }
    }
}

struct GroceryRow: View {
    @EnvironmentObject var store: HouseholdStore
    let item: GroceryItem
    var body: some View {
        HStack {
            Button { Task { await store.mark(item) } } label: { Image(systemName: item.isDone ? "checkmark.circle.fill" : "circle").font(.title2) }
                .buttonStyle(.borderless).accessibilityIdentifier("grocery-toggle-\(item.itemId)")
                .accessibilityLabel("Mark \(item.name) \(item.isDone ? "needed" : "purchased")")
                .disabled(store.busy || store.offline)
            VStack(alignment: .leading) {
                Text(item.name).strikethrough(item.isDone)
                Text(item.amount + " " + item.unit).font(.caption).foregroundStyle(.secondary)
                if item.excluded { Text("Already at home").font(.caption) }
                if item.needsReview { Text("Quantity changed from \(item.previousAmount ?? "the earlier plan"). Please review.").font(.caption).foregroundStyle(.orange) }
            }
        }
        .contextMenu { Button("Already at home") { Task { await store.own(item) } }.disabled(store.busy || store.offline) }
    }
}

struct AddGroceryView: View {
    @EnvironmentObject var store: HouseholdStore
    @Environment(\.dismiss) var dismiss
    @State private var name = ""
    @State private var amount = "1"
    @State private var unit = "each"
    var body: some View {
        Form {
            TextField("Item", text: $name)
            TextField("Amount", text: $amount).keyboardType(.decimalPad)
            TextField("Unit", text: $unit)
            ErrorSection()
            Button("Add to shared list") { Task { await store.perform {
                guard let api = store.api, let list = store.groceries else { return }
                store.groceries = try await api.addGrocery(to: list, name: name, amount: amount, unit: unit)
                dismiss()
            } } }.disabled(name.isEmpty || store.busy || store.offline)
        }
        .navigationTitle("Add shopping item").toolbar { Button("Cancel") { dismiss() } }
    }
}
