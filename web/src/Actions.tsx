/**
 * Compatibility entry point for action components.
 * Keep this facade because page modules and existing integrations import the
 * historical path; implementations live beside their domain concerns.
 */
export { AlarmOperations } from "./components/AlarmActions";
export type { Suppression } from "./api";
export { CreateUserForm } from "./components/UserActions";
