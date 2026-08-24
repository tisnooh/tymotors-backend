-- GTI and R are visually and technically distinct Golf 7 trims. They must be
-- selectable independently so one trim image is never presented as the other.

update public.vehicle_generations vg
set slug = 'gti',
    name = 'GTI',
    chassis_codes = array['Golf VII'],
    trims = array['GTI'],
    year_from = 2013,
    year_to = 2019,
    display_order = 1,
    updated_at = now()
from public.vehicle_models vm
join public.brands b on b.id = vm.brand_id
where vg.vehicle_model_id = vm.id
  and b.slug = 'volkswagen'
  and vm.slug = 'golf-7'
  and vg.slug = 'gti-r';

insert into public.vehicle_generations (
  vehicle_model_id, slug, name, chassis_codes, trims, year_from, year_to,
  display_order, is_active
)
select vm.id, 'r', 'R', array['Golf VII'], array['R'], 2013, 2020, 2, true
from public.vehicle_models vm
join public.brands b on b.id = vm.brand_id
where b.slug = 'volkswagen' and vm.slug = 'golf-7'
on conflict (vehicle_model_id, slug) do update
set name = excluded.name,
    chassis_codes = excluded.chassis_codes,
    trims = excluded.trims,
    year_from = excluded.year_from,
    year_to = excluded.year_to,
    display_order = excluded.display_order,
    updated_at = now();

