# RadMon Responsive Mobile-First UI Design

Date: 2026-09-14
Branch: `feature`
Status: Approved design, pending implementation plan

> Temporary engineering spec. Remove this file before final merge/release so the repository keeps the existing cleanup invariant that excludes `docs/superpowers` from production history.

## 1. Purpose

Refactor the authenticated RadMon web control plane into a robust, compact, mobile-first application while preserving the existing desktop control-plane experience and backend/security model.

The redesign must fix current layout defects, inconsistent spacing, viewport under-utilization, overlapping or fragile responsive behavior, thin single-component pages, and animation/state behavior that can visually break during navigation or realtime refresh.

The target is a single RadMon application with shared routes, authentication, RBAC, API calls, realtime refresh, and domain logic, but adaptive presentation for desktop, tablet, and mobile.

## 2. Non-negotiable product constraints

- Keep the existing backend architecture: FastAPI, authenticated RadMon sessions, server-side RBAC, REST source of truth, and SSE refresh hints.
- Keep the existing Kumo design system and Cloudflare-style control-plane language. Do not introduce a separate custom design system.
- Preserve the existing BRIN branding: BRIN logo as the product mark, no decorative letter `R` badges, no duplicate BRIN wordmark outside the logo where the logo already contains the text.
- Do not reintroduce decorative navigation icons. Navigation should remain visually restrained and primarily text-led.
- Mobile must feel like a native mobile operations app, not a desktop page shrunk to a narrow viewport.
- Desktop must remain a dense control plane with sidebar navigation and must not be degraded by the mobile-first implementation.
- Source MariaDB schemas remain read-only and unchanged.
- No new always-on frontend service. The app remains a static React/Vite bundle served by RadMon.
- No heavyweight runtime dependency is added to the Dell server.

## 3. Existing problems to address

The current frontend is primarily desktop-first. Its CSS starts with four-column desktop grids and reduces them through `max-width` breakpoints. The authenticated app always renders a Kumo sidebar shell, including narrow viewports. Several pages are compositionally weak; for example, Stations is effectively page heading plus one table, while Users permanently exposes a large create-user form.

Tables are the default representation even on small screens, causing horizontal scrolling instead of an app-like mobile layout. The current page shell also lacks an explicit viewport/safe-area contract for mobile browser chrome, fixed navigation, and dialog sizing.

The redesign must fix these structural issues rather than only adding more CSS patches.

## 4. Chosen architecture: adaptive single application

Use one shared route/data/state layer with two presentation shells:

- `DesktopShell` for desktop and large tablet landscape.
- `MobileShell` for small screens.
- Shared page/domain components underneath, with desktop/mobile presentation variants only when the information shape genuinely differs.

Do not build two separate applications. Do not duplicate API calls or authorization logic. Shared state survives responsive transitions where valid.

Recommended structure:

```text
web/src/
  layout/
    DesktopShell.tsx
    MobileShell.tsx
    MobileMoreSheet.tsx
  components/
    ResponsiveDataView.tsx
    StatusSummary.tsx
    StationCard.tsx
    StationTable.tsx
    PageSection.tsx
    MetricGrid.tsx
    EmptyState.tsx
    ErrorState.tsx
    SkeletonState.tsx
  pages/
    OverviewPage.tsx
    StationsPage.tsx
    HistoryPage.tsx
    ArchivesPage.tsx
    AlarmsPage.tsx
    UsersPage.tsx
    SystemPage.tsx
```

Existing files may be evolved instead of recreated where that keeps changes smaller, but responsibilities should move toward these boundaries.

## 5. Responsive shell contract

### 5.1 Breakpoints

```text
< 640 px      Mobile app
640-1023 px   Tablet/adaptive
>= 1024 px    Desktop control plane
```

The implementation should use mobile-first CSS: base styles target mobile, then progressively enhance for larger viewports.

### 5.2 Desktop >= 1024 px

- Kumo sidebar remains the primary navigation.
- Main content fills all remaining horizontal and vertical space.
- Shell minimum height is `100dvh`.
- Do not constrain the entire application to a narrow max-width.
- Max-width is only used for intrinsically narrow content such as forms or confirmation panels.
- Data grids use available space with `minmax(0, 1fr)` and adaptive column count.
- Tables use the full available width and only gain internal horizontal scrolling when the dataset actually requires it.
- Page headings and actions must wrap without overlap.
- Dense pages should use the viewport effectively; unnecessary empty right-side space is not acceptable.

### 5.3 Tablet 640-1023 px

- Sidebar may be compact/collapsible where supported by Kumo without layout instability.
- Two-column grids are used when content fits.
- Header actions wrap safely.
- No page-level horizontal overflow.
- Tables may scroll internally if needed, but shell and page body must remain width-stable.

### 5.4 Mobile < 640 px

- Desktop sidebar is not rendered.
- Use a compact sticky top application bar with BRIN logo and current page title.
- Use a sticky bottom navigation with safe-area padding.
- Shell uses `100dvh` and must account for mobile browser chrome and device safe areas.
- Main content receives bottom padding equal to or greater than the bottom-navigation height so the final control cannot be hidden behind navigation.
- Cards use consistent 12-16 px page margins and compact internal spacing.
- Desktop tables become mobile record cards/lists rather than forcing a 760 px table into a horizontal scroller.
- Dialogs become near-full-width sheets or constrained full-height modal surfaces as appropriate.
- Touch targets should be at least approximately 44 px tall/wide.
- No decorative icon-only navigation.

## 6. Mobile navigation model

The bottom navigation is role-aware.

### Viewer

- Overview
- Stations
- History
- More

### Operator and Administrator

- Overview
- Stations
- Alarms
- More

`More` opens a mobile sheet/menu containing the remaining allowed routes and account actions:

- History when not already pinned to bottom navigation
- Archives
- Users for Administrator only
- System for Administrator only
- Full Monitoring
- User/profile context
- Sign out

Navigation remains permission-aware in the frontend for usability, while backend role enforcement remains authoritative.

Browser Back/Forward must continue to work. Direct refresh of `/app/history`, `/app/system`, and other deep routes must preserve the same route instead of falling back to Overview.

## 7. Layout and spacing system

Use a small, consistent spacing rhythm based on 4/8/12/16/24/32 px increments.

Rules:

- Adjacent sections use consistent vertical rhythm.
- Card internal padding is consistent by density class rather than page-specific magic numbers.
- Related metrics use one grid instead of multiple isolated cards with arbitrary margins.
- Long text must either wrap intentionally or truncate with accessible full-value context.
- `min-width: 0` is required on flexible children that can otherwise force overflow.
- Avoid `100vw` for shell widths where browser scrollbars can create horizontal overflow.
- Sticky/fixed surfaces must reserve their own space in layout.
- No content may sit underneath the mobile top bar or bottom navigation.
- No page should depend on absolute positioning for primary layout.

## 8. Page composition and workflow

Every page must contain multiple relevant elements when the domain supports them. Do not add filler cards solely to increase component count.

### 8.1 Overview

Desktop:

- Status metrics: Normal, Warning, Alarm, Offline.
- Attention panel listing current Warning/Alarm/Offline stations.
- Freshness summary, including latest live measurement age/time.
- Full station health table.

Mobile:

- 2x2 compact status metric grid.
- Attention cards immediately after metrics.
- Station health cards.
- Freshness context visible without opening another route.

Workflow:

1. User opens Overview.
2. User sees overall system state immediately.
3. Abnormal/stale stations appear before healthy-detail noise.
4. User selects a station and can continue to station context/history.

Stale data must never look healthy simply because the last numerical measurement was under the warning threshold.

### 8.2 Stations

Desktop:

- Summary counters/context.
- Search and status/location filters.
- Station list/table.
- Contextual detail panel for the selected station where practical.

Mobile:

- Sticky/compact search.
- Filter chips or equivalent compact filters.
- Station cards containing name, location, status, dose rate, and last update.
- Selecting a station opens detail in a sheet or in-page detail region optimized for narrow screens.

Station detail should expose relevant metadata already present in the shared station model:

- SERID
- location
- current status
- dose rate
- warning threshold
- alarm threshold
- last measurement timestamp
- freshness
- link/action to History

### 8.3 History

Desktop:

- Station selector.
- Range/record-window controls where supported by the existing backend.
- Dose-rate trend visualization.
- Summary metrics: Latest, Minimum, Maximum, Average over the currently loaded range.
- Recent measurement table.

Mobile:

- Compact station selector.
- Full-width chart.
- Summary metrics in a 2x2 grid.
- Chronological measurement cards rather than a wide desktop table.

The frontend may calculate summary statistics from the fetched history dataset; do not add backend work solely for values that can be computed cheaply from already-loaded records.

### 8.4 Archives

Desktop:

- Archive summary: total bundles, latest period, and verification state where data exists.
- Period filters such as quarter/year when supported by returned archive metadata.
- Archive table.

Mobile:

- Compact archive summary.
- Period filter.
- Archive record cards showing period, verification/retention state, and relevant metadata.

Do not fabricate metrics that the archive API does not provide.

### 8.5 Alarms

Operational priority order:

1. Active alarms.
2. Alarm counters/context.
3. Respond/Suppress actions.
4. Recent policy-event history.

Desktop:

- Active alarms in a prominent section above history.
- Compact alarm status metrics.
- Response and timed-suppression actions.
- Event history table/list.

Mobile:

- Active alarm cards first.
- Sticky or highly reachable action region.
- Respond and Suppress open mobile-friendly sheets/dialogs.
- Event history becomes compact cards.

Existing alarm security semantics remain unchanged:

- operator/admin role required;
- PIN/PIC/reason requirements remain enforced server-side;
- PIN/password fields are cleared on close, success, and failure according to the existing security contract;
- realtime state refreshes after a successful operation.

Action buttons must enter a pending/disabled state during mutation to prevent double submission.

### 8.6 Users

Desktop:

- Summary: total users and role/enabled counts where derivable from the returned user list.
- Main user table/list.
- `Create user` is an explicit action opening a Kumo Dialog, not a permanent full-page form.

Mobile:

- Compact role/user summary.
- User cards.
- Sticky or clearly reachable `Create user` action.
- User creation uses a mobile-friendly sheet/dialog.

Secrets remain write-only. Password and PIN hashes must never be rendered.

### 8.7 System

The page must answer: "Is RadMon central and each LAN source healthy?"

Desktop:

- Service/runtime status.
- Source health summary.
- Source health table.
- Grafana admin action for Administrator.

Mobile:

- Service status card.
- Source cards for each LAN source.
- Secondary administrative actions below diagnostic content.

Source state should be human-readable, including available fields such as online/offline state, last success, last failure, or last live poll. Raw object dumps should not be the primary UX.

Grafana admin remains an Administrator action and is not promoted into the normal Viewer/Operator workflow.

## 9. Shared data and responsive presentation

API/data state is shared between desktop and mobile.

Do not fetch duplicate datasets purely because two presentation variants exist.

Use a responsive data-view abstraction when useful:

- desktop representation: Kumo table/grid;
- mobile representation: card/list;
- same typed data input;
- same actions and permissions;
- same loading/error state.

Resize/orientation changes must not reset the current route or selected station if the selection remains valid.

## 10. Loading, error, empty, and realtime states

### Loading

- Use skeleton/placeholder regions with stable dimensions where practical.
- Loading must not cause large layout jumps when data resolves.

### Error

- Component-local failures should render inside the affected section rather than replacing the entire page when other sections still have valid data.
- Page-level fatal errors remain possible when the core dataset cannot be loaded.

### Empty

- Empty states must explain what is empty in domain terms.
- Empty state surfaces should not consume excessive viewport height.

### Realtime

- SSE remains a lightweight refresh hint only.
- REST remains authoritative.
- Realtime updates must not flash/re-render the entire page unnecessarily.
- Values/cards may update in place with subtle transition.

## 11. Animation and motion safety

Animations exist only to clarify state transitions.

Allowed examples:

- dialog/sheet open and close;
- mobile More sheet;
- sidebar collapse where applicable;
- loading-to-content fade/transition;
- small state/value transition;
- filter/tab state transitions.

Rules:

- Typical transition duration: roughly 120-220 ms.
- Avoid large translating backgrounds or decorative motion.
- No animation may change business state.
- No animation may temporarily cover an actionable alarm or submit result.
- Respect `prefers-reduced-motion` and reduce/remove nonessential transitions.
- Body scroll must lock correctly while modal sheets/dialogs are open.
- Animation must not create horizontal overflow or viewport jumping.

## 12. Workflow correctness

- Mutations have pending/disabled states.
- Prevent double submit.
- Success/error feedback remains visible long enough for the user to understand the result.
- Session expiry returns the user to RadMon login with a clean authenticated state.
- Frontend role gating is convenience only; server-side authorization remains mandatory.
- Browser Back/Forward remains functional.
- Deep-route refresh remains functional.
- Responsive shell changes do not reset valid domain state.
- Forms containing PIN/password values clear secret fields on close/success/failure per security requirements.

## 13. Branding and visual restraint

- BRIN logo is the only product brand mark in login and application chrome.
- No letter `R` icon/badge anywhere in the RadMon web application.
- No unnecessary decorative navigation icon set.
- Logo must preserve aspect ratio and must not stretch, crop, or display a visible opaque background artifact.
- Login remains centered and visually balanced.
- Desktop and mobile use the same brand asset.

## 14. Performance constraints

The Dell production host has only 6 GB RAM and remains on the existing Windows installation.

Frontend changes must remain static-build only.

- No Node SSR runtime.
- No runtime browser automation.
- No heavy client state framework is required solely for responsiveness.
- Browser automation may run in CI/build jobs only.
- Charts should use an existing lightweight/Kumo-compatible implementation if already available; do not add a heavyweight charting stack unless necessary.
- Avoid loading large historical datasets by default.

## 15. QA and verification matrix

The UI is not considered complete solely because TypeScript and Vite build successfully.

Representative viewport coverage:

| Target | Viewport |
| --- | ---: |
| Small mobile | 360x800 |
| Common mobile | 390x844 |
| Large mobile | 430x932 |
| Tablet portrait | 768x1024 |
| Tablet landscape | 1024x768 |
| Laptop | 1366x768 |
| Desktop | 1920x1080 |

Routes/workflows to validate:

- Login
- Overview
- Stations
- History
- Archives
- Alarms for Operator and Administrator
- Users for Administrator
- System for Administrator
- Open/close dialog or sheet
- Mobile More menu
- Bottom navigation
- Long username/text values
- Empty datasets
- Error states
- 15-station dataset
- Active-alarm state
- Resize/orientation change

Automated regression expectations:

- no page-level horizontal overflow;
- mobile bottom nav does not cover final content/action;
- desktop sidebar is not rendered in mobile layout;
- mobile shell is not rendered in desktop layout;
- dialogs/actions remain reachable within viewport;
- BRIN logo is not stretched/cropped;
- no letter `R` badges/icons reappear;
- role-aware mobile navigation is correct;
- route/deep-link behavior remains correct;
- mobile and desktop presentation render the same authoritative domain state;
- pages identified as compositionally thin are upgraded with relevant supporting information.

## 16. CI strategy

Continue existing frontend checks:

- `npm ci`
- TypeScript check
- Vite production build

Add responsive/browser smoke coverage in CI where practical. Browser automation is build-time only and must not become a production dependency on the Dell server.

Continue backend/full regression:

- Python test suite
- compileall
- Grafana payload validation
- Windows EXE build
- packaged smoke test
- installer build
- fresh-install smoke test
- upgrade-over-running-RadMon smoke test

## 17. Acceptance criteria

The redesign is complete when all of the following are true:

1. Mobile is genuinely app-like with top app bar, role-aware bottom navigation, and More sheet.
2. Desktop retains a Kumo sidebar control-plane layout and uses available viewport space efficiently.
3. Tablet behavior is stable and does not overlap or overflow.
4. No primary content or control is hidden behind fixed navigation or browser safe areas.
5. No page-level horizontal overflow exists at the defined QA viewports.
6. Data tables have mobile card/list equivalents where wide tables are inappropriate.
7. Overview prioritizes abnormal/stale attention states and freshness.
8. Stations provides search/filter plus usable station detail context.
9. History provides trend visualization plus Latest/Min/Max/Avg and recent measurements.
10. Archives provides relevant summary/filter/list composition without fabricated metrics.
11. Alarms prioritizes active alarms and protects mutation workflow against double submit.
12. Users moves create-user into Dialog/sheet and keeps secrets write-only.
13. System presents human-readable source health instead of raw dump as the primary UX.
14. Realtime updates do not cause full-page flashing or destructive layout shifts.
15. Motion honors reduced-motion preferences and does not break layout.
16. Deep links, Back/Forward, resize, and orientation changes preserve valid route/state.
17. BRIN branding remains correct and all decorative `R` icons/badges remain absent.
18. Automated responsive/UI regression coverage passes alongside the existing full backend and Windows installer pipelines.
19. The production application remains static-build only with no new heavy always-on runtime dependency.
20. This temporary spec and the implementation plan are removed before final merge/release to preserve the repository cleanup policy.
