import XCTest
@testable import MealRoulette

final class HouseholdAPITests: XCTestCase {
    func testNewPlanDefaultsToUpcomingMondayLikeTheWebClient() {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let sunday = calendar.date(from: DateComponents(year: 2026, month: 11, day: 8))!
        let monday = calendar.date(from: DateComponents(year: 2026, month: 11, day: 9))!
        XCTAssertEqual(upcomingMonday(from: sunday, calendar: calendar), monday)
        XCTAssertEqual(upcomingMonday(from: monday, calendar: calendar), monday)
    }

    @MainActor
    func testPhoneCacheCanBeReadWithoutAConnectionAndClearedLocally() async throws {
        let connected = HouseholdStore()
        await connected.connect(address: "http://127.0.0.1:5057")
        XCTAssertNil(connected.errorMessage)
        XCTAssertNotNil(connected.lastSynced)
        let cached = HouseholdStore()
        XCTAssertTrue(cached.offline)
        XCTAssertFalse(cached.plans.isEmpty)
        XCTAssertNotNil(cached.groceries)
        cached.clearCache()
        XCTAssertNil(cached.lastSynced)
        let empty = HouseholdStore()
        XCTAssertNil(empty.lastSynced)
        XCTAssertTrue(empty.plans.isEmpty)
    }

    func testAddressesRejectNonHTTPAndEmbeddedCredentials() throws {
        XCTAssertThrowsError(try HouseholdAPI(address: "file:///tmp/meal"))
        XCTAssertThrowsError(try HouseholdAPI(address: "https://user:password@example.com"))
        XCTAssertNoThrow(try HouseholdAPI(address: "https://household.example.ts.net:8445"))
    }

    func testNativeClientPerformsLiveHouseholdWorkflow() async throws {
        let api = try HouseholdAPI(address: "http://127.0.0.1:5057")
        let health = try await api.health()
        XCTAssertEqual(health.status, "ok")
        XCTAssertGreaterThanOrEqual(health.schemaVersion, 2)
        let collection = try await api.collection()
        XCTAssertEqual(collection.eaters.filter { $0.active == 1 }.count, 2)
        XCTAssertGreaterThanOrEqual(collection.meals.count, 9)
        var plan = try await api.createPlan(week: "2027-01-04", mealTypes: ["dinner"])
        XCTAssertEqual(plan.assignments.count, 14)
        XCTAssertEqual(Set(plan.assignments.compactMap(\.mealId)).count, 7)
        let before = plan
        plan = try await api.confirm(plan)
        XCTAssertEqual(plan.state, "confirmed")
        do {
            _ = try await api.confirm(before)
            XCTFail("A stale revision must be rejected")
        } catch ServerFailure.response(let status, _) { XCTAssertEqual(status, 409) }
        plan = try await api.change(plan.assignments[0], in: plan, action: "leftovers")
        XCTAssertEqual(plan.assignments[0].kind, "leftovers")
        let grocery = try await api.groceries(plan.planId)
        XCTAssertTrue(grocery.warnings.isEmpty)
        let item = try XCTUnwrap(grocery.items.first)
        let marked = try await api.mark(item, in: grocery, checked: true)
        XCTAssertTrue(marked.items.contains { $0.itemId == item.itemId && $0.checked })
        do {
            _ = try await api.mark(item, in: grocery, checked: false)
            XCTFail("An outdated shopping list must be rejected")
        } catch ServerFailure.response(let status, _) { XCTAssertEqual(status, 409) }
        let ingredients = try await api.ingredients(collection.meals[0].mealId)
        XCTAssertFalse(ingredients.isEmpty)
        let preview = try await api.publish(plan, dryRun: true)
        XCTAssertTrue(preview.dryRun)
        XCTAssertEqual(preview.events, 14)
    }
}
