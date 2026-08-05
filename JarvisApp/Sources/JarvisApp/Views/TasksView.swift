import SwiftUI

/// Phase D: interne Aufgabenverwaltung, getrennt von Apple Reminders
/// (CalendarRemindersView). Automatisch erkannte Aufgaben landen mit Status
/// "vorgeschlagen" und müssen erst bestätigt werden (app/core/task_manager.py).
struct TasksView: View {
    @EnvironmentObject private var appState: AppState
    @State private var newTaskTitle = ""
    @State private var newTaskPriority = "mittel"
    @State private var taskPendingDeletion: JarvisTask?

    private let priorities = ["niedrig", "mittel", "hoch", "kritisch"]

    private var openTasks: [JarvisTask] {
        appState.tasks.filter { $0.status == "offen" || $0.status == "in_arbeit" }
    }
    private var proposedTasks: [JarvisTask] {
        appState.tasks.filter { $0.status == "vorgeschlagen" }
    }
    private var doneTasks: [JarvisTask] {
        appState.tasks.filter { $0.status == "erledigt" }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                newTaskBar
                if !proposedTasks.isEmpty {
                    section("Vorschläge - noch nicht bestätigt", tasks: proposedTasks, tint: .yellow)
                }
                section("Offen", tasks: openTasks, tint: .blue)
                if !doneTasks.isEmpty {
                    section("Erledigt", tasks: doneTasks, tint: .green)
                }
            }
            .padding(28)
            .frame(maxWidth: 1040, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(LiquidGlassBackground())
        .navigationTitle("Aufgaben")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await appState.refreshTasks() }
                } label: {
                    Label("Aktualisieren", systemImage: "arrow.clockwise")
                }
            }
        }
        .task { await appState.refreshTasks() }
        .confirmationDialog("Aufgabe löschen?", isPresented: Binding(
            get: { taskPendingDeletion != nil },
            set: { if !$0 { taskPendingDeletion = nil } }
        ), titleVisibility: .visible) {
            Button("Löschen", role: .destructive) {
                if let task = taskPendingDeletion {
                    Task { await appState.deleteTask(task) }
                }
                taskPendingDeletion = nil
            }
            Button("Abbrechen", role: .cancel) { taskPendingDeletion = nil }
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 16) {
            LiquidGlassIcon(symbol: "checkmark.circle", tint: .blue)
            VStack(alignment: .leading, spacing: 6) {
                Text("Aufgaben")
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                Text("Alltags- und Projektaufgaben, getrennt von Apple Erinnerungen. Automatisch erkannte Aufgaben werden erst nach deiner Bestätigung verbindlich.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .liquidGlassPanel(tint: .blue)
    }

    private var newTaskBar: some View {
        HStack(spacing: 10) {
            TextField("Neue Aufgabe ...", text: $newTaskTitle)
                .textFieldStyle(.roundedBorder)
                .onSubmit(submitNewTask)

            Picker("Priorität", selection: $newTaskPriority) {
                ForEach(priorities, id: \.self) { priority in
                    Text(priorityLabel(priority)).tag(priority)
                }
            }
            .frame(maxWidth: 160)

            Button("Hinzufügen", action: submitNewTask)
                .buttonStyle(.borderedProminent)
                .disabled(newTaskTitle.trimmingCharacters(in: .whitespaces).isEmpty)
        }
    }

    private func submitNewTask() {
        let title = newTaskTitle.trimmingCharacters(in: .whitespaces)
        guard !title.isEmpty else { return }
        Task { await appState.createTask(title: title, priority: newTaskPriority) }
        newTaskTitle = ""
    }

    private func section(_ title: String, tasks: [JarvisTask], tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title)
                .font(.title3.bold())
            VStack(spacing: 10) {
                ForEach(tasks) { task in
                    taskRow(task, tint: tint)
                }
            }
        }
    }

    private func taskRow(_ task: JarvisTask, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 10) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(task.title)
                        .font(.body)
                        .strikethrough(task.status == "erledigt")
                    HStack(spacing: 6) {
                        pill(priorityLabel(task.priority), tint: priorityTint(task.priority))
                        if let project = task.project, !project.isEmpty {
                            pill(project, tint: .purple)
                        }
                        if let deadline = task.deadline, !deadline.isEmpty {
                            pill(deadline, tint: .orange)
                        }
                        if appState.blockedTaskIDs.contains(task.id) {
                            pill("Blockiert", tint: .red)
                        }
                    }
                }
                Spacer(minLength: 12)
            }

            HStack(spacing: 8) {
                if task.status == "vorgeschlagen" {
                    Button("Bestätigen") { Task { await appState.confirmTask(task) } }
                        .buttonStyle(.bordered)
                    Button("Ablehnen") { Task { await appState.rejectTask(task) } }
                        .buttonStyle(.bordered)
                } else if task.status != "erledigt" {
                    Button("Erledigt") {
                        Task { await appState.updateTask(task, fields: ["status": "erledigt"]) }
                    }
                    .buttonStyle(.bordered)
                }
                Button("Löschen", role: .destructive) { taskPendingDeletion = task }
                    .buttonStyle(.bordered)
                Spacer()
            }
        }
        .padding(12)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(Color.white.opacity(0.14), lineWidth: 1)
        )
    }

    private func pill(_ text: String, tint: Color) -> some View {
        Text(text)
            .font(.caption2.weight(.semibold))
            .foregroundStyle(tint)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(tint.opacity(0.12), in: Capsule())
    }

    private func priorityLabel(_ priority: String) -> String {
        priority.prefix(1).uppercased() + priority.dropFirst()
    }

    private func priorityTint(_ priority: String) -> Color {
        switch priority {
        case "hoch": return .orange
        case "kritisch": return .red
        case "niedrig": return .secondary
        default: return .blue
        }
    }
}
