import Foundation

struct HouseholdAPI {
    let baseURL: URL
    private let session: URLSession

    init(address: String) throws {
        guard let url = URL(string: address.trimmingCharacters(in: .whitespacesAndNewlines)),
              ["http", "https"].contains(url.scheme?.lowercased() ?? ""), url.host != nil,
              url.user == nil, url.password == nil, url.query == nil, url.fragment == nil else {
            throw ServerFailure.invalidAddress
        }
        baseURL = url
        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.timeoutIntervalForRequest = 25
        configuration.httpShouldSetCookies = false
        session = URLSession(configuration: configuration)
    }

    private func data(_ path: String, method: String = "GET", body: [String: Any]? = nil) async throws -> Data {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw ServerFailure.response(0, "The server did not return an HTTP response.") }
        guard (200..<300).contains(response.statusCode) else {
            let message = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            throw ServerFailure.response(response.statusCode, message?["error"] as? String ?? "The server could not save that change.")
        }
        return data
    }

    private func request<T: Decodable>(_ path: String, method: String = "GET", body: [String: Any]? = nil) async throws -> T {
        let response = try await data(path, method: method, body: body)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(T.self, from: response)
    }

    func health() async throws -> Health { try await request("api/health") }
    func collection() async throws -> HouseholdCollection { try await request("api/collection") }
    func plans() async throws -> [PlanSummary] { try await request("api/plans") }
    func plan(_ id: Int) async throws -> Plan { try await request("api/plans/\(id)") }
    func groceries(_ id: Int) async throws -> GroceryList { try await request("api/plans/\(id)/groceries") }
    func ingredients(_ meal: Int) async throws -> [MealIngredient] { try await request("api/meals/\(meal)/ingredients") }
    func createPlan(week: String, mealTypes: [String]) async throws -> Plan {
        try await request("api/plans", method: "POST", body: ["week_start": week, "meal_types": mealTypes])
    }
    func confirm(_ plan: Plan) async throws -> Plan {
        try await request("api/plans/\(plan.planId)/confirm", method: "POST", body: ["revision": plan.revision])
    }
    func regenerate(_ plan: Plan) async throws -> Plan {
        try await request("api/plans/\(plan.planId)/regenerate", method: "POST", body: ["revision": plan.revision])
    }
    func change(_ slot: Assignment, in plan: Plan, action: String, mealId: Int? = nil) async throws -> Plan {
        var body: [String: Any] = ["revision": plan.revision, "action": action]
        if let mealId { body["meal_id"] = mealId }
        return try await request("api/plans/\(plan.planId)/assignments/\(slot.eaterId)/\(slot.date)/\(slot.mealType)", method: "PATCH", body: body)
    }
    func override(_ plan: Plan, day: String, mealType: String, diners: [Int], shared: Bool, kind: String, effort: Int?, theme: String) async throws -> Plan {
        var body: [String: Any] = ["revision": plan.revision, "eater_ids": diners, "group_meal": shared, "kind": kind, "theme": theme]
        body["max_effort"] = effort.map { $0 as Any } ?? NSNull()
        return try await request("api/plans/\(plan.planId)/slots/\(day)/\(mealType)", method: "PATCH", body: body)
    }
    func mark(_ item: GroceryItem, in list: GroceryList, checked: Bool) async throws -> GroceryList {
        try await request("api/plans/\(list.planId)/groceries/\(item.itemId)", method: "PATCH", body: ["revision": list.revision, "checked": checked, "excluded": false, "needs_review": false])
    }
    func own(_ item: GroceryItem, in list: GroceryList) async throws -> GroceryList {
        try await request("api/plans/\(list.planId)/groceries/\(item.itemId)", method: "PATCH", body: ["revision": list.revision, "excluded": true, "checked": false, "needs_review": false])
    }
    func addGrocery(to list: GroceryList, name: String, amount: String, unit: String) async throws -> GroceryList {
        try await request("api/plans/\(list.planId)/groceries", method: "POST", body: ["revision": list.revision, "name": name, "amount": amount, "unit": unit])
    }
    func addMeal(name: String, type: String, effort: Int?, theme: String, servings: String) async throws -> Meal {
        var body: [String: Any] = ["meal_description": name, "meal_type": type, "theme": theme, "servings": servings]
        body["effort_level"] = effort.map { $0 as Any } ?? NSNull()
        return try await request("api/meals", method: "POST", body: body)
    }
    func updateMeal(_ meal: Meal, name: String, type: String, effort: Int?, theme: String, servings: String) async throws -> Meal {
        var body: [String: Any] = ["meal_description": name, "meal_type": type, "theme": theme, "servings": servings]
        body["effort_level"] = effort.map { $0 as Any } ?? NSNull()
        return try await request("api/meals/\(meal.mealId)", method: "PATCH", body: body)
    }
    func archiveMeal(_ meal: Meal) async throws { _ = try await data("api/meals/\(meal.mealId)", method: "DELETE") }
    func restoreMeal(_ meal: Meal) async throws -> Meal { try await request("api/meals/\(meal.mealId)", method: "PATCH", body: ["active": 1]) }
    func saveIngredients(meal: Int, entries: [[String: String]]) async throws -> [MealIngredient] {
        try await request("api/meals/\(meal)/ingredients", method: "PUT", body: ["ingredients": entries])
    }
    func addEater(name: String) async throws {
        let _: Eater = try await request("api/eaters", method: "POST", body: ["name": name])
    }
    func setPreference(eater: Int, meal: Int, approved: Bool) async throws {
        if approved { _ = try await data("api/preferences", method: "POST", body: ["eater_id": eater, "meal_id": meal]) }
        else { _ = try await data("api/preferences/\(eater)/\(meal)", method: "DELETE") }
    }
    func saveRoutine(day: Int, mealType: String, shared: Bool, kind: String, effort: Int?, theme: String) async throws {
        var body: [String: Any] = ["group_meal": shared, "kind": kind, "theme": theme]
        body["max_effort"] = effort.map { $0 as Any } ?? NSNull()
        let _: Routine = try await request("api/routines/\(day)/\(mealType)", method: "PUT", body: body)
    }
    func deleteRoutine(_ routine: Routine) async throws {
        _ = try await data("api/routines/\(routine.weekday)/\(routine.mealType)", method: "DELETE")
    }
    func publish(_ plan: Plan, dryRun: Bool) async throws -> Publication {
        try await request("api/plans/\(plan.planId)/publish", method: "POST", body: ["revision": plan.revision, "dry_run": dryRun])
    }
}
