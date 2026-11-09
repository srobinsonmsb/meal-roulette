import Foundation
import SwiftUI

@MainActor
final class HouseholdStore: ObservableObject {
    @Published var serverAddress: String
    @Published var collection = HouseholdCollection.empty
    @Published var plans: [PlanSummary] = []
    @Published var selectedPlan: Plan?
    @Published var groceries: GroceryList?
    @Published var busy = false
    @Published var offline = false
    @Published var errorMessage: String?
    @Published var notice: String?
    @Published var lastSynced: Date?
    @Published var calendarEnabled = false
    private(set) var api: HouseholdAPI?

    private struct Cache: Codable {
        let address: String
        let collection: HouseholdCollection
        let plans: [PlanSummary]
        let selectedPlan: Plan?
        let groceries: GroceryList?
        let savedAt: Date
    }
    private var cacheURL: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("household-cache.json")
    }
    init() {
        serverAddress = ProcessInfo.processInfo.environment["MEAL_ROULETTE_SERVER_URL"] ?? UserDefaults.standard.string(forKey: "householdServerURL") ?? ""
        if let data = try? Data(contentsOf: cacheURL), let cache = try? JSONDecoder().decode(Cache.self, from: data), cache.address == serverAddress {
            collection = cache.collection; plans = cache.plans; selectedPlan = cache.selectedPlan
            groceries = cache.groceries; lastSynced = cache.savedAt; offline = true
        }
    }
    private func cache() {
        let value = Cache(address: serverAddress, collection: collection, plans: plans, selectedPlan: selectedPlan, groceries: groceries, savedAt: Date())
        do {
            try FileManager.default.createDirectory(at: cacheURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try JSONEncoder().encode(value).write(to: cacheURL, options: [.atomic, .completeFileProtection])
            lastSynced = value.savedAt
        } catch { notice = "Connected, but this phone could not save an offline copy." }
    }
    func connect(address: String? = nil) async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do {
            let chosen = address ?? serverAddress
            let next = try HouseholdAPI(address: chosen)
            let health = try await next.health()
            guard health.status == "ok", health.schemaVersion >= 2 else { throw ServerFailure.incompatibleServer }
            if chosen != serverAddress { clearCache(); selectedPlan = nil; groceries = nil; collection = .empty; plans = [] }
            serverAddress = chosen
            api = next
            calendarEnabled = health.calendarEnabled ?? false
            UserDefaults.standard.set(chosen, forKey: "householdServerURL")
            try await load()
            offline = false
        } catch {
            offline = true
            errorMessage = error.localizedDescription
        }
    }
    private func load() async throws {
        guard let api else { return }
        collection = try await api.collection()
        plans = try await api.plans()
        if let id = selectedPlan?.planId ?? plans.first?.planId {
            selectedPlan = try await api.plan(id)
            groceries = try await api.groceries(id)
        }
        cache()
    }
    func refresh() async {
        if api == nil || offline { await connect(); return }
        await perform { try await self.load() }
    }
    func perform(_ operation: () async throws -> Void) async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do { try await operation(); offline = false; cache() }
        catch {
            if error is URLError { offline = true }
            errorMessage = error.localizedDescription
        }
    }
    func select(_ id: Int) async {
        await perform {
            guard let api = self.api else { throw ServerFailure.invalidAddress }
            self.selectedPlan = try await api.plan(id)
            self.groceries = try await api.groceries(id)
        }
    }
    func create(week: String, mealTypes: [String]) async {
        await perform {
            guard let api = self.api else { throw ServerFailure.invalidAddress }
            self.selectedPlan = try await api.createPlan(week: week, mealTypes: mealTypes)
            try await self.load()
        }
    }
    func confirm() async {
        await perform {
            guard let api = self.api, let plan = self.selectedPlan else { return }
            self.selectedPlan = try await api.confirm(plan)
            try await self.load()
        }
    }
    func regenerate() async {
        await perform {
            guard let api = self.api, let plan = self.selectedPlan else { return }
            self.selectedPlan = try await api.regenerate(plan)
            try await self.load()
        }
    }
    func change(_ slot: Assignment, action: String, mealId: Int? = nil) async {
        await perform {
            guard let api = self.api, let plan = self.selectedPlan else { return }
            self.selectedPlan = try await api.change(slot, in: plan, action: action, mealId: mealId)
            try await self.load()
        }
    }
    func mark(_ item: GroceryItem) async {
        await perform {
            guard let api = self.api, let list = self.groceries else { return }
            self.groceries = try await api.mark(item, in: list, checked: !item.isDone)
        }
    }
    func own(_ item: GroceryItem) async {
        await perform {
            guard let api = self.api, let list = self.groceries else { return }
            self.groceries = try await api.own(item, in: list)
        }
    }
    func reloadAfterCollectionChange() async throws { try await load() }
    func clearCache() {
        try? FileManager.default.removeItem(at: cacheURL)
        lastSynced = nil
    }
    func disconnect() {
        clearCache(); api = nil; serverAddress = ""; collection = .empty; plans = []
        selectedPlan = nil; groceries = nil; offline = false; errorMessage = nil
        UserDefaults.standard.removeObject(forKey: "householdServerURL")
    }
}
