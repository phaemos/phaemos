# Machines pages

| Route | File | Description |
|---|---|---|
| /devices | page.tsx | The machines as a table with a search, filters, a sort, Add a machine and Update firmware by tag (admins only). The search, filters and sort live in the address (`?q=`, `status`, `tag`, `sort`) |
| /devices/[id] | [id]/page.tsx | One machine: details, owner and tags, the live chart, the latest reading of each sensor and a CSV export |

The route stays `/devices`. The interface says "machines". Supporting parts live in `components/machines/` and the pure logic in `lib/machineList.ts`, `lib/readingGroups.ts` and `lib/exportFile.ts`.
