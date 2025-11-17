module.exports = {
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 2022,
    sourceType: 'module',
    project: './tsconfig.json',
    tsconfigRootDir: __dirname,
  },
  plugins: ['@typescript-eslint'],
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
  ],
  env: {
    node: true,
    es2022: true,
    jest: true,
  },
  rules: {
    // TypeScript specific
    '@typescript-eslint/explicit-function-return-type': 'off',
    '@typescript-eslint/no-explicit-any': 'warn',
    '@typescript-eslint/no-unused-vars': [
      'error',
      {
        argsIgnorePattern: '^_',
        varsIgnorePattern: '^_',
      },
    ],

    // General
    'no-console': 'off', // Allow console.log in Lambda
    'prefer-const': 'error',
    'no-var': 'error',

    // Disable import rules - Lambda uses runtime-provided modules
    'import/no-unresolved': 'off',
    'import/namespace': 'off',
    'import/order': 'off',
    'import/no-duplicates': 'off',
  },
  ignorePatterns: ['dist', 'node_modules', 'cdk.out', '*.js'],
};
