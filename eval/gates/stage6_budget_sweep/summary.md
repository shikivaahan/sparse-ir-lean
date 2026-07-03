# stage6_budget_sweep

Verdict: budget sweep complete; coverage and cost as a function of reasoning budget.

- Problems evaluated per budget: 200.
- Budgets evaluated: 0, 256, 512, 1024, 2048, 4096, 8192, full.
- Wall-clock time: 258.2 min.
- Total cost: $1.928553.

## Verifier-value-vs-budget

| budget | coverage | cost USD | median reason tok | max reason tok | truncations |
| --- | --- | --- | --- | --- | --- |
| 0 | 88.0% | 0.159945 | 0 | 4 | 1 |
| 256 | 92.5% | 0.234500 | 1964 | 32768 | 1 |
| 512 | 92.5% | 0.243979 | 1870 | 59056 | 0 |
| 1024 | 92.5% | 0.259164 | 1548 | 62213 | 1 |
| 2048 | 93.5% | 0.254176 | 2048 | 32769 | 3 |
| 4096 | 91.5% | 0.255101 | 2298 | 32768 | 3 |
| 8192 | 92.5% | 0.261934 | 2182 | 32768 | 5 |
| full | 96.0% | 0.259754 | 1854 | 30379 | 2 |

## Cost per verified-correct

- budget `0`: $0.000909
- budget `256`: $0.001268
- budget `512`: $0.001319
- budget `1024`: $0.001401
- budget `2048`: $0.001359
- budget `4096`: $0.001394
- budget `8192`: $0.001416
- budget `full`: $0.001353

## Budget x house bin

| budget \ houses | 2 | 3 | 4 | 5 | 6 |
| --- | --- | --- | --- | --- | --- |
| 0 | 40/40 | 40/40 | 38/40 | 33/40 | 25/40 |
| 256 | 39/40 | 38/40 | 39/40 | 36/40 | 33/40 |
| 512 | 39/40 | 39/40 | 37/40 | 35/40 | 35/40 |
| 1024 | 39/40 | 38/40 | 40/40 | 32/40 | 36/40 |
| 2048 | 39/40 | 40/40 | 38/40 | 36/40 | 34/40 |
| 4096 | 38/40 | 39/40 | 40/40 | 36/40 | 30/40 |
| 8192 | 38/40 | 39/40 | 40/40 | 36/40 | 32/40 |
| full | 40/40 | 40/40 | 39/40 | 38/40 | 35/40 |

## Budget x grid

| budget \ grid | 2x2 | 2x3 | 2x4 | 2x5 | 2x6 | 3x2 | 3x3 | 3x4 | 3x5 | 3x6 | 4x2 | 4x3 | 4x4 | 4x5 | 4x6 | 5x2 | 5x3 | 5x4 | 5x5 | 5x6 | 6x2 | 6x3 | 6x4 | 6x5 | 6x6 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 7/8 | 7/8 | 8/8 | 8/8 | 8/8 | 6/8 | 7/8 | 4/8 | 8/8 | 6/8 | 4/8 | 4/8 | 3/8 |
| 256 | 8/8 | 8/8 | 8/8 | 8/8 | 7/8 | 8/8 | 7/8 | 8/8 | 7/8 | 8/8 | 7/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 7/8 | 7/8 | 6/8 | 7/8 | 8/8 | 6/8 | 7/8 | 5/8 |
| 512 | 8/8 | 8/8 | 8/8 | 8/8 | 7/8 | 8/8 | 8/8 | 8/8 | 7/8 | 8/8 | 8/8 | 8/8 | 7/8 | 7/8 | 7/8 | 7/8 | 7/8 | 8/8 | 7/8 | 6/8 | 7/8 | 7/8 | 8/8 | 7/8 | 6/8 |
| 1024 | 8/8 | 8/8 | 8/8 | 8/8 | 7/8 | 8/8 | 8/8 | 7/8 | 8/8 | 7/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 6/8 | 6/8 | 6/8 | 6/8 | 8/8 | 8/8 | 6/8 | 8/8 | 6/8 |
| 2048 | 8/8 | 8/8 | 8/8 | 8/8 | 7/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 6/8 | 8/8 | 8/8 | 6/8 | 7/8 | 7/8 | 8/8 | 8/8 | 8/8 | 7/8 | 6/8 | 5/8 |
| 4096 | 8/8 | 8/8 | 7/8 | 8/8 | 7/8 | 8/8 | 8/8 | 8/8 | 8/8 | 7/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 6/8 | 6/8 | 5/8 | 7/8 | 7/8 | 7/8 | 4/8 |
| 8192 | 8/8 | 7/8 | 8/8 | 8/8 | 7/8 | 8/8 | 8/8 | 8/8 | 8/8 | 7/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 7/8 | 7/8 | 6/8 | 8/8 | 8/8 | 7/8 | 6/8 | 6/8 | 5/8 |
| full | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 7/8 | 8/8 | 8/8 | 8/8 | 7/8 | 7/8 | 8/8 | 8/8 | 8/8 | 8/8 | 7/8 | 6/8 | 6/8 |

## Readable samples

### budget `0` solved `zl_lgp-test-2x2-10`

Lean verdict: `ACCEPT_SOLVED/solved`.

Reasoning excerpt: 

### budget `256` solved `zl_lgp-test-2x2-10`

Lean verdict: `ACCEPT_SOLVED/solved`.

Reasoning excerpt: We need to solve the puzzle. The puzzle has two categories: CarModel (ford f150, tesla model 3) and Name (Eric, Arnold). There are 2 houses (numbered 1 and 2). Clues: 1. c1: same_house: CarModel ford f150 and Name Arnold are in the same house. 2. c2: found_at: Name Arnold is at house 1. So from c2, Arnold is at house 1. Then from c1, ford f150 is in the same house as Arnold, so ford f150 is also at house 1. Then house 2 must have the remaining: Name Eric and CarModel tesla model 3. Thus solution

### budget `512` solved `zl_lgp-test-2x2-10`

Lean verdict: `ACCEPT_SOLVED/solved`.

Reasoning excerpt: We are given a puzzle with 2 categories: CarModel and Name, each with 2 values. There are 2 houses (1 and 2). Clues: c1: same_house: CarModel "ford f150" and Name "Arnold" are in the same house. c2: found_at: Name "Arnold" is at house 1. From c2, Arnold is at house 1. Then from c1, ford f150 is in the same house as Arnold, so ford f150 is also at house 1. Then the remaining values: CarModel "tesla model 3" must be at house 2, and Name "Eric" must be at house 2. Thus solution: House 1: CarModel: 

### budget `1024` solved `zl_lgp-test-2x2-10`

Lean verdict: `ACCEPT_SOLVED/solved`.

Reasoning excerpt: We need to solve a small zebra puzzle. Categories: CarModel (ford f150, tesla model 3) and Name (Eric, Arnold). Two houses (1 and 2). Clues: c1: same_house: ford f150 and Arnold are in the same house. c2: found_at: Arnold is at house 1. So from c2, Arnold is at house 1. Then from c1, ford f150 is also at house 1 (same house). So house 1: Name=Arnold, CarModel=ford f150. Then house 2 must have the remaining: Name=Eric, CarModel=tesla model 3. Thus solution: Name: 1: Arnold, 2: Eric; CarModel: 1: 

### budget `2048` solved `zl_lgp-test-2x2-10`

Lean verdict: `ACCEPT_SOLVED/solved`.

Reasoning excerpt: We need to solve a 2x2 zebra puzzle. Categories: CarModel (ford f150, tesla model 3) and Name (Eric, Arnold). Houses: 1 and 2. Clues: c1: same_house: ford f150 and Arnold are in same house. c2: found_at: Arnold is at house 1. So from c2: Arnold at house 1. From c1: ford f150 is same house as Arnold, so ford f150 at house 1. Therefore, house 1: Name Arnold, CarModel ford f150. Then house 2: Name Eric, CarModel tesla model 3 (since remaining). Thus solution: Name: 1:Arnold, 2:Eric; CarModel: 1:for

### budget `4096` solved `zl_lgp-test-2x2-10`

Lean verdict: `ACCEPT_SOLVED/solved`.

Reasoning excerpt: We need to solve this logic puzzle. The puzzle is a 2x2 grid: 2 houses, 2 categories (CarModel and Name). The clues: 1. Clue c1: same_house: CarModel "ford f150" and Name "Arnold" are in the same house. 2. Clue c2: found_at: Name "Arnold" is at house 1. So from c2, Arnold is in house 1. Then from c1, ford f150 is in the same house as Arnold, so ford f150 is also in house 1. Then the remaining values: Name Eric must be in house 2, and CarModel tesla model 3 must be in house 2. Thus solution: Hous

### budget `8192` solved `zl_lgp-test-2x2-10`

Lean verdict: `ACCEPT_SOLVED/solved`.

Reasoning excerpt: We are given a puzzle with 2 categories: CarModel and Name, each with 2 values. There are 2 houses (1 and 2). Clues: c1: same_house: ford f150 and Arnold are in the same house. c2: found_at: Arnold is at house 1. From c2: Arnold is at house 1. From c1: ford f150 is in the same house as Arnold, so ford f150 is also at house 1. Then the remaining values: the other Name is Eric, and the other CarModel is tesla model 3. They must be at house 2 (since house 1 is occupied by Arnold and ford f150). So 

### budget `full` solved `zl_lgp-test-2x2-10`

Lean verdict: `ACCEPT_SOLVED/solved`.

Reasoning excerpt: We are given a puzzle with 2 categories: CarModel and Name, each with 2 values. There are 2 houses. Clues: 1. c1: same_house: CarModel ford f150 and Name Arnold are in the same house. 2. c2: found_at: Name Arnold is at house 1. From c2, Arnold is at house 1. Then from c1, ford f150 is in the same house as Arnold, so ford f150 is also at house 1. That means the other car (tesla model 3) must be at house 2, and the other name (Eric) must be at house 2. So the solution is: House 1: CarModel: ford f
