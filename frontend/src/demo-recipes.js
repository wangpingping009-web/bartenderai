function recipe(id, name, name_cn, base_spirit, abv, glass, method, ingredients, steps, flavor, timer_seconds = 0) {
  const [sweet, sour, bitter, aroma, body] = flavor
  return {
    id, name, name_cn, base_spirit, abv, glass, method, steps, timer_seconds,
    timer_label: '摇和计时',
    alcoholic: abv > 0,
    category: 'Cocktail',
    flavor: { sweet, sour, bitter, aroma, body, strong: Math.round(abv / 4) },
    ingredients: ingredients.map(([name, name_zh, amount]) => ({ name, name_zh, amount })),
    equipment: method === '摇和' ? ['量酒器', '摇酒壶', '滤冰器'] : ['量酒器', '吧勺'],
  }
}

export default [
  recipe('negroni', 'Negroni', '内格罗尼', 'gin', 22, 'old-fashioned glass', '搅拌',
    [['gin', '金酒', '30 ml'], ['campari', '金巴利', '30 ml'], ['sweet vermouth', '甜味美思', '30 ml'], ['orange peel', '橙皮', '1 片']],
    ['在古典杯里放入一块大冰。', '倒入金酒、金巴利和甜味美思，搅拌至酒液冰凉。', '在杯口挤出橙皮油，再将橙皮放入杯中。'], [5, 1, 8, 8, 6]),
  recipe('daiquiri', 'Daiquiri', '得其利', 'rum', 23, 'cocktail glass', '摇和',
    [['white rum', '白朗姆', '60 ml'], ['lime juice', '青柠汁', '25 ml'], ['simple syrup', '糖浆', '15 ml']],
    ['提前冰镇鸡尾酒杯。', '将白朗姆、鲜榨青柠汁和糖浆倒入摇酒壶。', '加冰摇和约 12 秒，滤入冰镇的鸡尾酒杯。'], [6, 8, 1, 6, 4], 12),
  recipe('mojito', 'Mojito', '莫吉托', 'rum', 10, 'highball glass', '直调',
    [['white rum', '白朗姆', '45 ml'], ['lime juice', '青柠汁', '20 ml'], ['simple syrup', '糖浆', '15 ml'], ['mint', '薄荷', '8 片'], ['soda water', '苏打水', '80 ml']],
    ['将青柠汁、糖浆和薄荷放入高球杯，轻轻按压薄荷。', '加入白朗姆和冰块，用吧勺稍作搅拌。', '补满苏打水，轻提杯底酒液，用薄荷装饰。'], [6, 6, 1, 9, 3]),
  recipe('margarita', 'Margarita', '玛格丽特', 'tequila', 24, 'cocktail glass', '摇和',
    [['tequila', '龙舌兰', '50 ml'], ['triple sec', '橙味利口酒', '20 ml'], ['lime juice', '青柠汁', '25 ml'], ['salt', '盐', '少许']],
    ['用青柠擦过半圈杯口，再蘸少量细盐。', '将龙舌兰、橙味利口酒和青柠汁倒入摇酒壶。', '加冰摇和约 12 秒，滤入备好的鸡尾酒杯。'], [4, 8, 2, 7, 5], 12),
  recipe('whiskey-sour', 'Whiskey Sour', '威士忌酸', 'whiskey', 21, 'old-fashioned glass', '摇和',
    [['bourbon', '波本威士忌', '60 ml'], ['lemon juice', '柠檬汁', '25 ml'], ['simple syrup', '糖浆', '20 ml']],
    ['准备一只放入大冰块的古典杯。', '将波本、鲜榨柠檬汁和糖浆倒入摇酒壶。', '加冰摇和约 12 秒，滤入古典杯。'], [6, 8, 2, 6, 6], 12),
  recipe('moscow-mule', 'Moscow Mule', '莫斯科骡子', 'vodka', 10, 'highball glass', '直调',
    [['vodka', '伏特加', '45 ml'], ['lime juice', '青柠汁', '15 ml'], ['ginger beer', '姜汁啤酒', '110 ml']],
    ['在高球杯中加满冰块。', '倒入伏特加和青柠汁。', '加入姜汁啤酒，轻搅一下后用青柠片装饰。'], [5, 5, 1, 8, 4]),
  recipe('mint-lime-soda', 'Mint Lime Soda', '薄荷青柠苏打', '', 0, 'highball glass', '直调',
    [['lime juice', '青柠汁', '25 ml'], ['simple syrup', '糖浆', '15 ml'], ['mint', '薄荷', '8 片'], ['soda water', '苏打水', '120 ml']],
    ['将薄荷、青柠汁和糖浆放入杯中，轻轻按压薄荷。', '加冰，倒入冷藏过的苏打水。', '用吧勺轻提杯底糖浆，以一枝薄荷收尾。'], [5, 7, 1, 9, 2]),
  recipe('orange-ginger-fizz', 'Orange Ginger Fizz', '橙香姜汁气泡饮', '', 0, 'highball glass', '直调',
    [['orange juice', '橙汁', '70 ml'], ['lemon juice', '柠檬汁', '15 ml'], ['ginger ale', '无酒精姜汁汽水', '100 ml']],
    ['在高球杯中放入冰块。', '倒入橙汁和柠檬汁，稍作搅拌。', '倒入冷藏的无酒精姜汁汽水，用橙片装饰。'], [7, 5, 1, 8, 3]),
]
