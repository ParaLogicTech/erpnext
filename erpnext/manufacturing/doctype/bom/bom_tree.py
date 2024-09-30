class BOMGraph:
	def __init__(self, bom_nos):
		self.graph = {}
		self.bom_nos = bom_nos

	def add_edge(self, parent, child):
		self.graph.setdefault(parent, []).append(child)

	def topological_sort(self, parent_bom=None):
		visited = set()
		stack = []

		if parent_bom:
			bom_list = [parent_bom]
		else:
			bom_list = self.bom_nos

		for bom_no in bom_list:
			if bom_no not in visited:
				self._topological_sort_util(bom_no, visited, stack)

		return stack

	def _topological_sort_util(self, bom_no, visited, stack):
		visited.add(bom_no)

		for child_bom in self.graph.get(bom_no, []):
			if child_bom not in visited:
				self._topological_sort_util(child_bom, visited, stack)

		stack.append(bom_no)
