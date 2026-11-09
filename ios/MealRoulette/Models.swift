import Foundation

struct Health: Decodable { let status: String; let schemaVersion: Int; let calendarEnabled: Bool? }

struct Eater: Codable, Identifiable {
    let eaterId: Int
    var name: String
    var active: Int
    var id: Int { eaterId }
}

struct Meal: Codable, Identifiable {
    let mealId: Int
    var mealDescription: String
    var mealType: String
    var effortLevel: Int?
    var theme: String
    var servings: String
    var active: Int
    var id: Int { mealId }
}

struct Preference: Codable { let eaterId: Int; let mealId: Int }
struct Ingredient: Codable, Identifiable {
    let ingredientId: Int
    var name: String
    var normalizedName: String
    var id: Int { ingredientId }
}
struct MealIngredient: Codable, Identifiable {
    let mealId: Int
    let ingredientId: Int
    let name: String
    let amount: String
    let unit: String
    var id: String { "\(ingredientId):\(unit)" }
}
struct Routine: Codable, Identifiable {
    let routineId: Int
    let weekday: Int
    let mealType: String
    let groupMeal: Int
    let kind: String
    let maxEffort: Int?
    let theme: String
    var id: Int { routineId }
}
struct HouseholdCollection: Codable {
    var eaters: [Eater]
    var meals: [Meal]
    var preferences: [Preference]
    var ingredients: [Ingredient]
    var routines: [Routine]
    static let empty = HouseholdCollection(eaters: [], meals: [], preferences: [], ingredients: [], routines: [])
}
struct PlanSummary: Codable, Identifiable {
    let planId: Int
    let weekStart: String
    let state: String
    let revision: Int
    var id: Int { planId }
}
struct Assignment: Codable, Identifiable {
    let planId: Int
    let eaterId: Int
    let date: String
    let mealType: String
    let mealId: Int?
    let groupMeal: Bool
    let kind: String
    let eaterName: String
    let mealName: String?
    let reason: String?
    let maxEffort: Int?
    let theme: String
    let manual: Int
    var id: String { "\(planId):\(eaterId):\(date):\(mealType)" }
    var label: String {
        switch kind {
        case "eating_out": return "Eating out"
        case "leftovers": return "Leftovers"
        default: return mealName ?? "No meal assigned"
        }
    }
}
struct CalendarJob: Codable { let requestedRevision: Int; let attempts: Int; let lastError: String? }
struct Plan: Codable, Identifiable {
    let planId: Int
    let weekStart: String
    let state: String
    let revision: Int
    let mealTypes: [String]
    let assignments: [Assignment]
    let calendarJob: CalendarJob?
    var id: Int { planId }
}
struct GroceryItem: Codable, Identifiable {
    let itemId: Int
    let name: String
    let amount: String
    let unit: String
    let previousAmount: String?
    let checked: Bool
    let excluded: Bool
    let manual: Bool
    let needsReview: Bool
    var id: Int { itemId }
    var isDone: Bool { checked || excluded }
}
struct GroceryList: Codable {
    let planId: Int
    let weekStart: String
    let revision: Int
    let items: [GroceryItem]
    let warnings: [String]
}
struct Publication: Decodable { let dryRun: Bool; let events: Int }

enum ServerFailure: LocalizedError {
    case response(Int, String)
    case invalidAddress
    case incompatibleServer
    var errorDescription: String? {
        switch self {
        case .response(_, let message): return message
        case .invalidAddress: return "Enter your household server's http or https address."
        case .incompatibleServer: return "Update the household server before using this client."
        }
    }
}
