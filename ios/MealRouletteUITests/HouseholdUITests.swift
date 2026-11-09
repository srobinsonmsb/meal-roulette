import XCTest

final class HouseholdUITests: XCTestCase {
    func testNativePlanningMealsAndSharedGroceries() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchEnvironment["MEAL_ROULETTE_SERVER_URL"] = "http://127.0.0.1:5057"
        app.launch()
        let groceriesTab = app.tabBars.buttons["Groceries"]
        XCTAssertTrue(groceriesTab.waitForExistence(timeout: 30))
        XCTAssertTrue(app.navigationBars["Weekly plans"].waitForExistence(timeout: 30))
        groceriesTab.tap()
        let toggle = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "grocery-toggle-")).firstMatch
        XCTAssertTrue(toggle.waitForExistence(timeout: 30))
        let oldLabel = toggle.label
        toggle.tap()
        let changed = NSPredicate(format: "label != %@", oldLabel)
        expectation(for: changed, evaluatedWith: toggle)
        waitForExpectations(timeout: 30)
        app.tabBars.buttons["Meals"].tap()
        XCTAssertTrue(app.navigationBars["Meals"].waitForExistence(timeout: 10))
        app.tabBars.buttons["Settings"].tap()
        XCTAssertTrue(app.staticTexts["Members and preferences"].waitForExistence(timeout: 10))
    }
}
