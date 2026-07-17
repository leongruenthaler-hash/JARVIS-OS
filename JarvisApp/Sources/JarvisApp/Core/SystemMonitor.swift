import Foundation
import IOKit.ps

/// Reads native macOS system stats (CPU, RAM, battery) directly via Mach host-statistics
/// and IOKit power-source APIs - no external dependencies, no network calls, no Python
/// round-trip. Built as a standalone data source for the dashboard-theme feature (Datenquelle
/// 1/4); not yet wired into any UI.
struct SystemStats {
    let cpuUsagePercent: Double
    let memoryUsagePercent: Double
    let batteryPercent: Int?
    let isCharging: Bool?
}

enum SystemMonitor {
    static func currentStats() async -> SystemStats {
        let cpu = await cpuUsagePercent() ?? 0
        let memory = memoryUsagePercent() ?? 0
        let battery = batteryInfo()
        return SystemStats(
            cpuUsagePercent: cpu,
            memoryUsagePercent: memory,
            batteryPercent: battery?.percentage,
            isCharging: battery?.isCharging
        )
    }

    /// CPU usage needs two samples of cumulative tick counts spaced apart in time - a
    /// single snapshot only gives ticks-since-boot, not a current percentage.
    static func cpuUsagePercent(sampleInterval: Duration = .milliseconds(300)) async -> Double? {
        guard let first = hostCPULoadInfo() else { return nil }
        try? await Task.sleep(for: sampleInterval)
        guard let second = hostCPULoadInfo() else { return nil }

        let userDiff = Double(second.cpu_ticks.0 &- first.cpu_ticks.0)
        let systemDiff = Double(second.cpu_ticks.1 &- first.cpu_ticks.1)
        let idleDiff = Double(second.cpu_ticks.2 &- first.cpu_ticks.2)
        let niceDiff = Double(second.cpu_ticks.3 &- first.cpu_ticks.3)
        let totalDiff = userDiff + systemDiff + idleDiff + niceDiff
        guard totalDiff > 0 else { return nil }

        let usedDiff = userDiff + systemDiff + niceDiff
        return max(0, min(100, (usedDiff / totalDiff) * 100))
    }

    private static func hostCPULoadInfo() -> host_cpu_load_info? {
        var size = mach_msg_type_number_t(MemoryLayout<host_cpu_load_info_data_t>.stride / MemoryLayout<integer_t>.stride)
        var cpuLoadInfo = host_cpu_load_info()
        let result = withUnsafeMutablePointer(to: &cpuLoadInfo) { pointer -> kern_return_t in
            pointer.withMemoryRebound(to: integer_t.self, capacity: Int(size)) { reboundPointer in
                host_statistics(mach_host_self(), HOST_CPU_LOAD_INFO, reboundPointer, &size)
            }
        }
        guard result == KERN_SUCCESS else { return nil }
        return cpuLoadInfo
    }

    /// Approximates "used" memory as active + wired + compressed pages (excludes free and
    /// inactive/purgeable pages, which macOS reclaims on demand) - matches roughly what
    /// Activity Monitor shows as "Memory Used", not raw allocated-vs-free.
    static func memoryUsagePercent() -> Double? {
        var size = mach_msg_type_number_t(MemoryLayout<vm_statistics64_data_t>.stride / MemoryLayout<integer_t>.stride)
        var stats = vm_statistics64()
        let result = withUnsafeMutablePointer(to: &stats) { pointer -> kern_return_t in
            pointer.withMemoryRebound(to: integer_t.self, capacity: Int(size)) { reboundPointer in
                host_statistics64(mach_host_self(), HOST_VM_INFO64, reboundPointer, &size)
            }
        }
        guard result == KERN_SUCCESS else { return nil }

        let pageSize = UInt64(vm_kernel_page_size)
        let active = UInt64(stats.active_count) * pageSize
        let wired = UInt64(stats.wire_count) * pageSize
        let compressed = UInt64(stats.compressor_page_count) * pageSize
        let used = active + wired + compressed

        let total = ProcessInfo.processInfo.physicalMemory
        guard total > 0 else { return nil }
        return max(0, min(100, (Double(used) / Double(total)) * 100))
    }

    /// Uses the public IOKit power-source API (IOPSCopyPowerSourcesInfo family) - no
    /// private/undocumented APIs, no `pmset` subprocess spawn.
    static func batteryInfo() -> (percentage: Int, isCharging: Bool)? {
        guard let snapshot = IOPSCopyPowerSourcesInfo()?.takeRetainedValue(),
              let sources = IOPSCopyPowerSourcesList(snapshot)?.takeRetainedValue() as? [CFTypeRef] else {
            return nil
        }
        for source in sources {
            guard let info = IOPSGetPowerSourceDescription(snapshot, source)?.takeUnretainedValue() as? [String: AnyObject] else {
                continue
            }
            guard let capacity = info[kIOPSCurrentCapacityKey] as? Int,
                  let maxCapacity = info[kIOPSMaxCapacityKey] as? Int,
                  maxCapacity > 0 else {
                continue
            }
            let percentage = Int((Double(capacity) / Double(maxCapacity)) * 100)
            let stateString = info[kIOPSPowerSourceStateKey] as? String
            let isCharging = stateString == kIOPSACPowerValue
            return (percentage, isCharging)
        }
        return nil
    }
}
