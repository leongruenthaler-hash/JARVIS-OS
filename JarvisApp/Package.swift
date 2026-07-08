// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "JarvisApp",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "JarvisApp", targets: ["JarvisApp"])
    ],
    targets: [
        .executableTarget(
            name: "JarvisApp",
            path: "Sources/JarvisApp"
        )
    ]
)
