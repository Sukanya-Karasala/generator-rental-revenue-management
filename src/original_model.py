from pyomo.environ import * 
import pandas as pd 
import numpy as np


data = pd.read_excel('Group_Assignment_Dataset.xlsx', sheet_name = 'Data', index_col = None)
print(f'==' * 30 )
print(f'Given Data from PLG Organisation')
print(f'--'* 30)
# Initial capacity available before horizon starts
initial_capacity = data.loc[2, 'Unnamed: 1']
print(f'Initial Capacity: {initial_capacity}')

# Total number of generators PLG has 
N = data.loc[1, 'Unnamed: 1']
print(f'Total number of Generators : {N}')

unit_cost = data.loc[3, 'Unnamed: 1']

print(f'Unit cost of Generators : {unit_cost}')


original_revenue = data.loc[2, 'Unnamed: 4']
original_load_factor = data.loc[3, 'Unnamed: 4']
original_roi = data.loc[4, 'Unnamed: 4']

print(f'The original Revenue : {original_revenue}')
print(f'The original Load Factor : {original_load_factor}')
print(f'The original ROI: {original_roi}')


duration_of_weeks = data.loc[4, 'Unnamed: 1']
duration_of_weeks = duration_of_weeks.split(',')
duration_of_weeks = [int(x) for x in duration_of_weeks]
print(f'Duration of rental weeks available at PLG: {duration_of_weeks}') 


columns = data.loc[7, :].values

rental_chart = data[10:]
rental_chart.columns = columns
rental_chart = rental_chart.reset_index()

del rental_chart['index']


weeks = rental_chart['Week ']
week_count = rental_chart['WK#']


# For the return of first week before horizon 

bh_ret_week_1 = rental_chart.loc[:,  'Return'].iloc[:, 0].values
bh_ret_week_1 = bh_ret_week_1[:1]

bh_ret_week_4 = rental_chart.loc[:,  'Return'].iloc[:, 1].values
bh_ret_week_4 = bh_ret_week_4[:4]

bh_ret_week_8 = rental_chart.loc[:,  'Return'].iloc[:, 2].values
bh_ret_week_8 = bh_ret_week_8[:8]

bh_ret_week_16 = rental_chart.loc[:,  'Return'].iloc[:, 3].values
bh_ret_week_16 = bh_ret_week_16[:16]


demand_matrix = np.array(rental_chart.loc[:, 'Demand'])
demand_matrix = demand_matrix[:-1, :].astype(int)


rental_cost_matrix = np.array(rental_chart.loc[:, '£/Day'])
rental_cost_matrix = rental_cost_matrix[:-1, :].astype(float)

# Model 

model = ConcreteModel()

print(f'Total number of weeks :{len(weeks)}')
print(f'Total number of duration of weeks :{len(duration_of_weeks)}')

model.gen_rented = Var(range(len(weeks)-1), range(len(duration_of_weeks)), domain = NonNegativeIntegers)
model.inv = Var(range(len(weeks)-1), domain = NonNegativeReals) 

bh_returns = {t: 0 for t in range(len(weeks)-1)}

for week_idx in range(len(weeks)-1):
    if week_idx < len(bh_ret_week_1):  
        bh_returns[week_idx] += bh_ret_week_1[week_idx]
    if week_idx < len(bh_ret_week_4):  
        bh_returns[week_idx] += bh_ret_week_4[week_idx]
    if week_idx < len(bh_ret_week_8):  
        bh_returns[week_idx] += bh_ret_week_8[week_idx]
    if week_idx < len(bh_ret_week_16): 
        bh_returns[week_idx] += bh_ret_week_16[week_idx]

def maximise_obj(model):
    revenue = 0
    for i in range(len(weeks)-1):
        for j in range(len(duration_of_weeks)):
            revenue += model.gen_rented[i,j] * int(duration_of_weeks[j]) * 7 * rental_cost_matrix[i,j]
    return revenue 

model.objective = Objective(rule = maximise_obj, sense = maximize)


def less_than_demand_constraint(model, i, j):
    return model.gen_rented[i,j] <= demand_matrix[i,j]

model.demand_constraint = Constraint(range(len(weeks)-1), range(len(duration_of_weeks)), expr = less_than_demand_constraint)



def inventory_tracking(model, t):
    if t == 0:
        return model.inv[t] == initial_capacity + bh_returns[t]
    
    prev_accepted = 0
    for i in range(len(duration_of_weeks)):
        prev_accepted += model.gen_rented[t-1, i]
    
    lp_returns = 0
    for i in range(len(duration_of_weeks)):
        if t - int(duration_of_weeks[i]) >= 0:
            lp_returns += model.gen_rented[t - int(duration_of_weeks[i]), i]
    
    
    return model.inv[t] == model.inv[t-1] - prev_accepted + lp_returns + bh_returns[t]

model.inventory_tracking = Constraint(range(len(weeks)-1), rule=inventory_tracking)


def capacity_rule(model, t):
    sum = 0 
    for i in range(len(duration_of_weeks)):
        sum += model.gen_rented[t, i] 
    return sum <= model.inv[t]
        
    

model.cap_rule = Constraint(range(len(weeks)-1), rule=capacity_rule)


solver = SolverFactory('glpk')
solver.solve(model)

total_revenue = value(model.objective)
print(f'--' * 30)
print(f'Optimised Generated Revenue : {total_revenue:.2f}')
print(f'Original Revenue : {original_revenue}')
print(f'==' * 30)

generator_load_factor = (N - np.mean([value(model.inv[i]) for i in range(len(weeks) - 1)])) / N
print(f'Optimised Load Factor : {generator_load_factor:.2f}')
print(f'Original Load Factor : {original_load_factor}')

print(f'==' * 30)
roi = total_revenue / (N * unit_cost)
print(f'Optimised ROI : {roi:.2f}')
print(f'Original ROI : {original_roi}')

