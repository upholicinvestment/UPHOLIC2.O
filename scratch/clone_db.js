print("Cloning collections from Upholicfno to UPHOLIC2_O...");
var sourceDb = db.getSiblingDB("Upholicfno");

print("Cloning instruments...");
sourceDb.instruments.aggregate([ { $out: { db: "UPHOLIC2_O", coll: "instruments" } } ]);
print("instruments cloned.");

print("Cloning optstk_history_1m...");
sourceDb.optstk_history_1m.aggregate([ { $out: { db: "UPHOLIC2_O", coll: "optstk_history_1m" } } ]);
print("optstk_history_1m cloned.");

print("Ensuring indexes on target UPHOLIC2_O...");
var targetDb = db.getSiblingDB("UPHOLIC2_O");
targetDb.instruments.createIndex({ underlying_symbol: 1 });
targetDb.optstk_history_1m.createIndex({ symbol: 1, timestamp: 1 });
targetDb.optstk_history_1m.createIndex({ timestamp: 1 });
print("Indexes created. Cloning complete!");
