#!/usr/bin/env python3
"""Generate the checked-in Xcode project without XcodeGen or third-party tooling."""

import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
objects = {}


def identifier(name):
    return hashlib.sha256(name.encode()).hexdigest()[:24].upper()


def add(object_name, isa, **values):
    key = identifier(object_name)
    objects[key] = {"isa": isa, **values}
    return key


def encode(value, depth=0):
    if isinstance(value, dict):
        return "{\n" + "".join("\t" * (depth + 1) + encode(k) + " = " + encode(v, depth + 1) + ";\n" for k, v in value.items()) + "\t" * depth + "}"
    if isinstance(value, list):
        return "(" + ", ".join(encode(v, depth + 1) for v in value) + ("," if value else "") + ")"
    value = str(value)
    return value if re.fullmatch(r"[A-Za-z0-9_./]+", value) else json.dumps(value)


def configurations(name, settings):
    entries = []
    for mode in ("Debug", "Release"):
        values = dict(settings)
        values.update(SWIFT_OPTIMIZATION_LEVEL="-Onone" if mode == "Debug" else "-O")
        if mode == "Debug":
            values.update(ENABLE_TESTABILITY="YES", SWIFT_ACTIVE_COMPILATION_CONDITIONS="DEBUG")
        entries.append(add(name + mode, "XCBuildConfiguration", buildSettings=values, name=mode))
    return add(name + "configurations", "XCConfigurationList", buildConfigurations=entries, defaultConfigurationIsVisible="0", defaultConfigurationName="Release")


def main():
    project = identifier("project")
    targets = []
    products = []
    groups = []
    target_ids = {name: identifier("target:" + name) for name in ("MealRoulette", "MealRouletteTests", "MealRouletteUITests")}
    for name, target in target_ids.items():
        application = name == "MealRoulette"
        files = []
        builds = []
        for source in sorted((ROOT / name).glob("*.swift")):
            ref = add(str(source.relative_to(ROOT)), "PBXFileReference", lastKnownFileType="sourcecode.swift", path=str(source.relative_to(ROOT)), sourceTree="<group>")
            files.append(ref)
            builds.append(add(str(source.relative_to(ROOT)) + ":build", "PBXBuildFile", fileRef=ref))
        if application:
            files.append(add("Info.plist", "PBXFileReference", lastKnownFileType="text.plist.xml", path="MealRoulette/Info.plist", sourceTree="<group>"))
        groups.append(add(name + "group", "PBXGroup", name=name, children=files, sourceTree="<group>"))
        product = add(name + ":product", "PBXFileReference", explicitFileType="wrapper.application" if application else "wrapper.cfbundle", includeInIndex="0", path=name + (".app" if application else ".xctest"), sourceTree="BUILT_PRODUCTS_DIR")
        products.append(product)
        sources = add(name + ":sources", "PBXSourcesBuildPhase", buildActionMask="2147483647", files=builds, runOnlyForDeploymentPostprocessing="0")
        frameworks = add(name + ":frameworks", "PBXFrameworksBuildPhase", buildActionMask="2147483647", files=[], runOnlyForDeploymentPostprocessing="0")
        resources = add(name + ":resources", "PBXResourcesBuildPhase", buildActionMask="2147483647", files=[], runOnlyForDeploymentPostprocessing="0")
        settings = {
            "PRODUCT_NAME": "$(TARGET_NAME)", "PRODUCT_BUNDLE_IDENTIFIER": "org.mealroulette.household" + ("" if application else "." + name.lower()),
            "GENERATE_INFOPLIST_FILE": "YES", "SWIFT_VERSION": "5.0", "IPHONEOS_DEPLOYMENT_TARGET": "17.0",
            "TARGETED_DEVICE_FAMILY": "1,2", "MARKETING_VERSION": "0.3.0", "CURRENT_PROJECT_VERSION": "1", "CODE_SIGN_STYLE": "Automatic",
        }
        dependencies = []
        if application:
            settings.update(INFOPLIST_FILE="MealRoulette/Info.plist", INFOPLIST_KEY_UIApplicationSceneManifest_Generation="YES", INFOPLIST_KEY_UILaunchScreen_Generation="YES")
        else:
            proxy = add(name + ":proxy", "PBXContainerItemProxy", containerPortal=project, proxyType="1", remoteGlobalIDString=target_ids["MealRoulette"], remoteInfo="MealRoulette")
            dependencies.append(add(name + ":dependency", "PBXTargetDependency", target=target_ids["MealRoulette"], targetProxy=proxy))
            if name == "MealRouletteTests":
                settings.update(TEST_HOST="$(BUILT_PRODUCTS_DIR)/MealRoulette.app/MealRoulette", BUNDLE_LOADER="$(TEST_HOST)")
            else:
                settings.update(TEST_TARGET_NAME="MealRoulette")
        objects[target] = {
            "isa": "PBXNativeTarget", "name": name, "productName": name, "productReference": product,
            "buildConfigurationList": configurations(name, settings), "buildPhases": [sources, frameworks, resources],
            "buildRules": [], "dependencies": dependencies,
            "productType": "com.apple.product-type.application" if application else ("com.apple.product-type.bundle.ui-testing" if name.endswith("UITests") else "com.apple.product-type.bundle.unit-test"),
        }
        targets.append(target)
    product_group = add("products", "PBXGroup", name="Products", children=products, sourceTree="<group>")
    main_group = add("main-group", "PBXGroup", children=groups + [product_group], sourceTree="<group>")
    project_config = configurations("project", {"SDKROOT": "iphoneos", "SUPPORTED_PLATFORMS": "iphoneos iphonesimulator", "CLANG_ENABLE_MODULES": "YES", "IPHONEOS_DEPLOYMENT_TARGET": "17.0"})
    objects[project] = {
        "isa": "PBXProject", "attributes": {"LastUpgradeCheck": "1600", "TargetAttributes": {target_ids["MealRouletteTests"]: {"TestTargetID": target_ids["MealRoulette"]}, target_ids["MealRouletteUITests"]: {"TestTargetID": target_ids["MealRoulette"]}}},
        "buildConfigurationList": project_config, "compatibilityVersion": "Xcode 14.0", "developmentRegion": "en", "knownRegions": ["en", "Base"],
        "mainGroup": main_group, "productRefGroup": product_group, "projectDirPath": "", "projectRoot": "", "targets": targets,
    }
    path = ROOT / "MealRoulette.xcodeproj"
    path.mkdir(exist_ok=True)
    document = {"archiveVersion": "1", "classes": {}, "objectVersion": "56", "objects": objects, "rootObject": project}
    (path / "project.pbxproj").write_text("// !$*UTF8*$!\n" + encode(document) + "\n")
    scheme = ET.Element("Scheme", LastUpgradeVersion="1600", version="1.7")

    def reference(parent, name):
        return ET.SubElement(parent, "BuildableReference", BuildableIdentifier="primary", BlueprintIdentifier=target_ids[name], BuildableName=name + (".app" if name == "MealRoulette" else ".xctest"), BlueprintName=name, ReferencedContainer="container:MealRoulette.xcodeproj")

    build = ET.SubElement(scheme, "BuildAction", parallelizeBuildables="YES", buildImplicitDependencies="YES")
    entries = ET.SubElement(build, "BuildActionEntries")
    for name in target_ids:
        item = ET.SubElement(entries, "BuildActionEntry", buildForTesting="YES", buildForRunning="YES" if name == "MealRoulette" else "NO", buildForProfiling="YES" if name == "MealRoulette" else "NO", buildForArchiving="YES" if name == "MealRoulette" else "NO", buildForAnalyzing="YES")
        reference(item, name)
    test = ET.SubElement(scheme, "TestAction", buildConfiguration="Debug", selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB", selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB", shouldUseLaunchSchemeArgsEnv="YES")
    reference(ET.SubElement(test, "MacroExpansion"), "MealRoulette")
    testables = ET.SubElement(test, "Testables")
    for name in ("MealRouletteTests", "MealRouletteUITests"):
        reference(ET.SubElement(testables, "TestableReference", skipped="NO", parallelizable="NO"), name)
    launch = ET.SubElement(scheme, "LaunchAction", buildConfiguration="Debug", selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB", selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB", launchStyle="0", useCustomWorkingDirectory="NO", ignoresPersistentStateOnLaunch="NO", debugServiceExtension="internal", allowLocationSimulation="YES")
    reference(ET.SubElement(launch, "BuildableProductRunnable", runnableDebuggingMode="0"), "MealRoulette")
    ET.SubElement(scheme, "AnalyzeAction", buildConfiguration="Debug")
    ET.SubElement(scheme, "ArchiveAction", buildConfiguration="Release", revealArchiveInOrganizer="YES")
    folder = path / "xcshareddata/xcschemes"
    folder.mkdir(parents=True, exist_ok=True)
    ET.indent(scheme)
    ET.ElementTree(scheme).write(folder / "MealRoulette.xcscheme", encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
