import SwiftUI

@main
struct MealRouletteApp: App {
    @StateObject private var store = HouseholdStore()
    @Environment(\.scenePhase) private var scenePhase
    var body: some Scene {
        WindowGroup {
            RootView().environmentObject(store)
                .task { if !store.serverAddress.isEmpty { await store.connect() } }
                .onChange(of: scenePhase) { phase in
                    if phase == .active && !store.serverAddress.isEmpty { Task { await store.refresh() } }
                }
        }
    }
}

struct RootView: View {
    @EnvironmentObject var store: HouseholdStore
    var body: some View {
        VStack(spacing: 0) {
            if store.offline && store.lastSynced != nil {
                Text("Offline · showing saved household data. Reconnect to make changes.").font(.caption).padding().frame(maxWidth: .infinity).background(.yellow.opacity(0.2))
            }
            if store.serverAddress.isEmpty {
                NavigationStack { ServerSettingsView().navigationTitle("Connect your household") }
            } else {
                TabView {
                    NavigationStack { PlansView() }.tabItem { Label("Plan", systemImage: "calendar") }
                    NavigationStack { GroceriesView() }.tabItem { Label("Groceries", systemImage: "cart") }
                    NavigationStack { MealsView() }.tabItem { Label("Meals", systemImage: "fork.knife") }
                    NavigationStack { HouseholdSettingsView() }.tabItem { Label("Settings", systemImage: "house") }
                }
            }
        }
        .overlay(alignment: .top) { if store.busy { ProgressView().padding().background(.regularMaterial, in: Capsule()) } }
        .alert("Household update", isPresented: Binding(get: { store.errorMessage != nil }, set: { if !$0 { store.errorMessage = nil } })) {
            Button("Reload") { Task { await store.refresh() } }
            Button("OK", role: .cancel) { store.errorMessage = nil }
        } message: { Text(store.errorMessage ?? "") }
    }
}
